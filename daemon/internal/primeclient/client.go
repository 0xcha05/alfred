// Package primeclient provides a bidirectional TCP client for connecting to Ultron Prime.
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

	"github.com/ultron/daemon/internal/handlers"
)

// Client manages the bidirectional connection to Ultron Prime.
type Client struct {
	// Configuration
	primeAddress    string
	registrationKey string
	name            string
	hostname        string
	capabilities    []string
	isSoulDaemon    bool
	ultronRoot      string

	// Connection state
	conn     net.Conn
	daemonID string
	mu       sync.RWMutex

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
	UltronRoot      string
}

// Core message types (protocol level)
const (
	TypeRegistration    = "registration"
	TypeRegistrationAck = "registration_ack"
	TypeHeartbeat       = "heartbeat"
	TypeResult          = "result"
	TypeEvent           = "event"  // For proactive events from daemon
	TypePing            = "ping"
)

// Note: Command types like "shell", "read_file", etc. are now handled
// by the handler registry (handlers package), not hardcoded here.

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
		ultronRoot:      cfg.UltronRoot,
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
		"ultron_root":      c.ultronRoot,
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

	// Log incoming command from Prime
	log.Printf("📥 Command from Prime: type=%s, id=%s", msgType, commandID)
	if msgType == "shell" {
		if cmd, ok := msg["command"].(string); ok {
			log.Printf("   Shell: %s", cmd)
		}
	}

	// Use the handler registry - all command types are handled there
	// This makes the daemon extensible without modifying this code
	result := handlers.Handle(msgType, msg)

	// Log result
	success, _ := result["success"].(bool)
	if success {
		log.Printf("✅ Command %s completed successfully", commandID)
	} else {
		errMsg, _ := result["error"].(string)
		log.Printf("❌ Command %s failed: %s", commandID, errMsg)
	}

	// Add command_id and daemon_id to result
	result["command_id"] = commandID
	result["daemon_id"] = c.daemonID
	result["type"] = TypeResult

	// Send result back to Prime
	if err := c.sendMessage(result); err != nil {
		log.Printf("Failed to send result: %v", err)
	}
}

// SendEvent sends a proactive event to Prime.
func (c *Client) SendEvent(source, eventType string, payload map[string]interface{}) error {
	event := map[string]interface{}{
		"type":       TypeEvent,
		"daemon_id":  c.daemonID,
		"source":     source,
		"event_type": eventType,
		"payload":    payload,
		"timestamp":  time.Now().UTC().Format(time.RFC3339),
	}
	return c.sendMessage(event)
}

// NOTE: Command handlers are now in the handlers package (handlers.RegisterBuiltins())
// This keeps client.go focused on connection management only.

// SendAlert sends an alert to Prime.
func (c *Client) SendAlert(alertType, message, severity string, metadata map[string]string) error {
	msg := map[string]interface{}{
		"type":       "alert",
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
