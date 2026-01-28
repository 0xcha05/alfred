// Package primeclient provides a bidirectional TCP client for connecting to Alfred Prime.
// The daemon connects TO Prime (not the other way around), enabling daemons behind NAT.
package primeclient

import (
	"bufio"
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"runtime"
	"sync"
	"time"

	"github.com/alfred/daemon/internal/executor"
)

// Client manages the bidirectional connection to Alfred Prime.
type Client struct {
	// Configuration
	primeAddress    string
	registrationKey string
	name            string
	hostname        string
	capabilities    []string
	isSoulDaemon    bool
	alfredRoot      string

	// Connection state
	conn     net.Conn
	daemonID string
	mu       sync.RWMutex

	// Command execution
	executor *executor.Executor

	// Reconnection
	reconnectDelay time.Duration
	maxReconnect   time.Duration
}

// Config holds the client configuration.
type Config struct {
	PrimeAddress    string
	RegistrationKey string
	Name            string
	Hostname        string
	Capabilities    []string
	IsSoulDaemon    bool
	AlfredRoot      string
}

// Message types
const (
	TypeRegistration    = "registration"
	TypeRegistrationAck = "registration_ack"
	TypeHeartbeat       = "heartbeat"
	TypeResult          = "result"
	TypeAlert           = "alert"
	TypeShell           = "shell"
	TypeReadFile        = "read_file"
	TypeWriteFile       = "write_file"
	TypeDeleteFile      = "delete_file"
	TypeListFiles       = "list_files"
	TypeListProcesses   = "list_processes"
	TypeKillProcess     = "kill_process"
	TypeManageService   = "manage_service"
	TypeInstallPackage  = "install_package"
	TypeDocker          = "docker"
	TypeGit             = "git"
	TypeSession         = "session"
	TypeCron            = "cron"
	TypeSystemInfo      = "system_info"
	TypeSelfModify      = "self_modify"
	TypePing            = "ping"
)

// Message is the generic message structure.
type Message struct {
	Type      string                 `json:"type"`
	DaemonID  string                 `json:"daemon_id,omitempty"`
	CommandID string                 `json:"command_id,omitempty"`
	Data      map[string]interface{} `json:"-"`
}

// NewClient creates a new Prime client.
func NewClient(cfg Config) *Client {
	hostname := cfg.Hostname
	if hostname == "" {
		hostname, _ = os.Hostname()
	}

	return &Client{
		primeAddress:    cfg.PrimeAddress,
		registrationKey: cfg.RegistrationKey,
		name:            cfg.Name,
		hostname:        hostname,
		capabilities:    cfg.Capabilities,
		isSoulDaemon:    cfg.IsSoulDaemon,
		alfredRoot:      cfg.AlfredRoot,
		executor:        executor.New(),
		reconnectDelay:  1 * time.Second,
		maxReconnect:    60 * time.Second,
	}
}

// Connect establishes a connection to Prime and maintains it.
func (c *Client) Connect(ctx context.Context) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		err := c.connectOnce(ctx)
		if err != nil {
			log.Printf("Connection error: %v", err)
		}

		// Reconnect with backoff
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(c.reconnectDelay):
		}

		// Increase delay for next attempt (exponential backoff)
		c.reconnectDelay *= 2
		if c.reconnectDelay > c.maxReconnect {
			c.reconnectDelay = c.maxReconnect
		}
	}
}

func (c *Client) connectOnce(ctx context.Context) error {
	log.Printf("Connecting to Prime at %s...", c.primeAddress)

	// Dial with context
	var d net.Dialer
	conn, err := d.DialContext(ctx, "tcp", c.primeAddress)
	if err != nil {
		return fmt.Errorf("dial failed: %w", err)
	}

	c.mu.Lock()
	c.conn = conn
	c.mu.Unlock()

	defer func() {
		conn.Close()
		c.mu.Lock()
		c.conn = nil
		c.mu.Unlock()
	}()

	log.Printf("Connected to Prime")

	// Reset reconnect delay on successful connection
	c.reconnectDelay = 1 * time.Second

	// Send registration
	if err := c.sendRegistration(); err != nil {
		return fmt.Errorf("registration failed: %w", err)
	}

	// Start heartbeat goroutine
	heartbeatCtx, cancelHeartbeat := context.WithCancel(ctx)
	defer cancelHeartbeat()
	go c.heartbeatLoop(heartbeatCtx)

	// Read and process messages
	return c.messageLoop(ctx)
}

func (c *Client) sendRegistration() error {
	msg := map[string]interface{}{
		"type":             TypeRegistration,
		"registration_key": c.registrationKey,
		"name":             c.name,
		"hostname":         c.hostname,
		"capabilities":     c.capabilities,
		"is_soul_daemon":   c.isSoulDaemon,
		"alfred_root":      c.alfredRoot,
	}

	if err := c.sendMessage(msg); err != nil {
		return err
	}

	// Wait for registration ack
	ack, err := c.readMessage()
	if err != nil {
		return fmt.Errorf("reading ack: %w", err)
	}

	if ack["type"] != TypeRegistrationAck {
		return fmt.Errorf("unexpected message type: %v", ack["type"])
	}

	if success, ok := ack["success"].(bool); !ok || !success {
		return fmt.Errorf("registration rejected: %v", ack["message"])
	}

	if id, ok := ack["daemon_id"].(string); ok {
		c.daemonID = id
	}

	log.Printf("✓ Registered as %s (%s)", c.daemonID, c.name)
	return nil
}

func (c *Client) heartbeatLoop(ctx context.Context) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			c.sendHeartbeat()
		}
	}
}

func (c *Client) sendHeartbeat() {
	// Collect system stats
	var memPercent, cpuPercent, diskPercent float64

	// Simple approximations (could use gopsutil for more accurate stats)
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	memPercent = float64(m.Alloc) / float64(m.Sys) * 100

	msg := map[string]interface{}{
		"type":           TypeHeartbeat,
		"daemon_id":      c.daemonID,
		"cpu_percent":    cpuPercent,
		"memory_percent": memPercent,
		"disk_percent":   diskPercent,
		"active_tasks":   0,
	}

	if err := c.sendMessage(msg); err != nil {
		log.Printf("Heartbeat failed: %v", err)
	}
}

func (c *Client) messageLoop(ctx context.Context) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		// Set read deadline
		c.conn.SetReadDeadline(time.Now().Add(60 * time.Second))

		msg, err := c.readMessage()
		if err != nil {
			if err == io.EOF {
				return fmt.Errorf("connection closed")
			}
			if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
				// Read timeout, continue
				continue
			}
			return fmt.Errorf("read error: %w", err)
		}

		// Process message
		go c.handleMessage(msg)
	}
}

func (c *Client) handleMessage(msg map[string]interface{}) {
	msgType, _ := msg["type"].(string)
	commandID, _ := msg["command_id"].(string)

	var result map[string]interface{}
	var err error

	switch msgType {
	case TypePing:
		result = map[string]interface{}{
			"type":       TypeResult,
			"command_id": commandID,
			"success":    true,
			"output":     "pong",
		}

	case TypeShell:
		result = c.handleShell(msg)

	case TypeReadFile:
		result = c.handleReadFile(msg)

	case TypeWriteFile:
		result = c.handleWriteFile(msg)

	case TypeDeleteFile:
		result = c.handleDeleteFile(msg)

	case TypeListFiles:
		result = c.handleListFiles(msg)

	case TypeSystemInfo:
		result = c.handleSystemInfo(msg)

	case TypeDocker:
		result = c.handleDocker(msg)

	case TypeGit:
		result = c.handleGit(msg)

	case TypeListProcesses:
		result = c.handleListProcesses(msg)

	case TypeKillProcess:
		result = c.handleKillProcess(msg)

	case TypeManageService:
		result = c.handleManageService(msg)

	default:
		result = map[string]interface{}{
			"type":       TypeResult,
			"command_id": commandID,
			"success":    false,
			"error":      fmt.Sprintf("unknown command type: %s", msgType),
		}
	}

	// Add command_id and daemon_id to result
	result["command_id"] = commandID
	result["daemon_id"] = c.daemonID
	result["type"] = TypeResult

	if err != nil {
		result["success"] = false
		result["error"] = err.Error()
	}

	// Send result back to Prime
	if err := c.sendMessage(result); err != nil {
		log.Printf("Failed to send result: %v", err)
	}
}

// Command handlers

func (c *Client) handleShell(msg map[string]interface{}) map[string]interface{} {
	command, _ := msg["command"].(string)
	workDir, _ := msg["working_directory"].(string)
	useSudo, _ := msg["use_sudo"].(bool)

	if useSudo {
		command = "sudo " + command
	}

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	result, err := c.executor.ExecuteShell(ctx, command, workDir, nil, nil)
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success":   result.ExitCode == 0,
		"output":    result.Stdout,
		"error":     result.Stderr,
		"exit_code": result.ExitCode,
	}
}

func (c *Client) handleReadFile(msg map[string]interface{}) map[string]interface{} {
	path, _ := msg["path"].(string)

	content, err := c.executor.ReadFile(path)
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success": true,
		"output":  string(content),
	}
}

func (c *Client) handleWriteFile(msg map[string]interface{}) map[string]interface{} {
	path, _ := msg["path"].(string)
	content, _ := msg["content"].(string)
	createDirs, _ := msg["create_dirs"].(bool)

	// Decode base64 content if needed
	var data []byte
	data = []byte(content)

	err := c.executor.WriteFile(path, data, 0644, createDirs)
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success": true,
		"output":  fmt.Sprintf("Written %d bytes to %s", len(data), path),
	}
}

func (c *Client) handleDeleteFile(msg map[string]interface{}) map[string]interface{} {
	path, _ := msg["path"].(string)
	recursive, _ := msg["recursive"].(bool)

	var err error
	if recursive {
		err = os.RemoveAll(path)
	} else {
		err = os.Remove(path)
	}

	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success": true,
		"output":  fmt.Sprintf("Deleted %s", path),
	}
}

func (c *Client) handleListFiles(msg map[string]interface{}) map[string]interface{} {
	path, _ := msg["path"].(string)
	recursive, _ := msg["recursive"].(bool)

	files, err := c.executor.ListFiles(path, recursive)
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	// Convert to serializable format
	var fileList []map[string]interface{}
	for _, f := range files {
		fileList = append(fileList, map[string]interface{}{
			"name":         f.Name,
			"path":         f.Path,
			"size":         f.Size,
			"is_directory": f.IsDir,
			"modified_at":  f.ModTime.Unix(),
		})
	}

	return map[string]interface{}{
		"success": true,
		"output":  fileList,
	}
}

func (c *Client) handleSystemInfo(msg map[string]interface{}) map[string]interface{} {
	info, err := c.executor.GetSystemInfo()
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success": true,
		"output": map[string]interface{}{
			"hostname":    info.Hostname,
			"os":          info.OS,
			"arch":        info.Arch,
			"num_cpu":     info.NumCPU,
			"username":    info.Username,
			"home_dir":    info.HomeDir,
			"working_dir": info.WorkingDir,
			"pid":         info.PID,
		},
	}
}

func (c *Client) handleDocker(msg map[string]interface{}) map[string]interface{} {
	argsRaw, _ := msg["args"].([]interface{})
	workDir, _ := msg["working_directory"].(string)

	var args []string
	for _, a := range argsRaw {
		if s, ok := a.(string); ok {
			args = append(args, s)
		}
	}

	ctx := context.Background()
	result, err := c.executor.ManageDocker(ctx, args...)
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	_ = workDir // TODO: use working directory

	return map[string]interface{}{
		"success":   result.ExitCode == 0,
		"output":    result.Stdout,
		"error":     result.Stderr,
		"exit_code": result.ExitCode,
	}
}

func (c *Client) handleGit(msg map[string]interface{}) map[string]interface{} {
	argsRaw, _ := msg["args"].([]interface{})
	workDir, _ := msg["working_directory"].(string)

	var args []string
	for _, a := range argsRaw {
		if s, ok := a.(string); ok {
			args = append(args, s)
		}
	}

	ctx := context.Background()
	result, err := c.executor.GitOperation(ctx, workDir, args...)
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success":   result.ExitCode == 0,
		"output":    result.Stdout,
		"error":     result.Stderr,
		"exit_code": result.ExitCode,
	}
}

func (c *Client) handleListProcesses(msg map[string]interface{}) map[string]interface{} {
	ctx := context.Background()
	result, err := c.executor.GetProcessList(ctx)
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success": true,
		"output":  result.Stdout,
	}
}

func (c *Client) handleKillProcess(msg map[string]interface{}) map[string]interface{} {
	pidFloat, _ := msg["pid"].(float64)
	signalFloat, _ := msg["signal"].(float64)
	pid := int(pidFloat)
	signal := int(signalFloat)

	if signal == 0 {
		signal = 15 // SIGTERM
	}

	ctx := context.Background()
	cmd := fmt.Sprintf("kill -%d %d", signal, pid)
	result, err := c.executor.ExecuteShell(ctx, cmd, "", nil, nil)
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success": result.ExitCode == 0,
		"output":  result.Stdout,
		"error":   result.Stderr,
	}
}

func (c *Client) handleManageService(msg map[string]interface{}) map[string]interface{} {
	serviceName, _ := msg["service_name"].(string)
	action, _ := msg["action"].(string)

	ctx := context.Background()
	result, err := c.executor.ManageService(ctx, serviceName, action)
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success":   result.ExitCode == 0,
		"output":    result.Stdout,
		"error":     result.Stderr,
		"exit_code": result.ExitCode,
	}
}

// SendAlert sends an alert to Prime.
func (c *Client) SendAlert(alertType, message, severity string, metadata map[string]string) error {
	msg := map[string]interface{}{
		"type":       TypeAlert,
		"daemon_id":  c.daemonID,
		"alert_type": alertType,
		"message":    message,
		"severity":   severity,
		"metadata":   metadata,
	}
	return c.sendMessage(msg)
}

// Low-level message handling

func (c *Client) sendMessage(msg map[string]interface{}) error {
	c.mu.RLock()
	conn := c.conn
	c.mu.RUnlock()

	if conn == nil {
		return fmt.Errorf("not connected")
	}

	data, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}

	// Write length prefix (4 bytes, big-endian)
	length := make([]byte, 4)
	binary.BigEndian.PutUint32(length, uint32(len(data)))

	c.mu.Lock()
	defer c.mu.Unlock()

	if _, err := c.conn.Write(length); err != nil {
		return fmt.Errorf("write length: %w", err)
	}
	if _, err := c.conn.Write(data); err != nil {
		return fmt.Errorf("write data: %w", err)
	}

	return nil
}

func (c *Client) readMessage() (map[string]interface{}, error) {
	c.mu.RLock()
	conn := c.conn
	c.mu.RUnlock()

	if conn == nil {
		return nil, fmt.Errorf("not connected")
	}

	reader := bufio.NewReader(conn)

	// Read length prefix (4 bytes, big-endian)
	lengthBuf := make([]byte, 4)
	if _, err := io.ReadFull(reader, lengthBuf); err != nil {
		return nil, err
	}
	length := binary.BigEndian.Uint32(lengthBuf)

	// Read message data
	data := make([]byte, length)
	if _, err := io.ReadFull(reader, data); err != nil {
		return nil, err
	}

	var msg map[string]interface{}
	if err := json.Unmarshal(data, &msg); err != nil {
		return nil, fmt.Errorf("unmarshal: %w", err)
	}

	return msg, nil
}

// Close closes the connection.
func (c *Client) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.conn != nil {
		return c.conn.Close()
	}
	return nil
}

// DaemonID returns the assigned daemon ID.
func (c *Client) DaemonID() string {
	return c.daemonID
}

// IsConnected returns true if connected to Prime.
func (c *Client) IsConnected() bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.conn != nil
}
