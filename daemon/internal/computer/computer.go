// Package computer provides Anthropic Computer Use capabilities.
// It communicates with a Python subprocess that handles screenshot capture
// and mouse/keyboard control on macOS.
package computer

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
)

// Manager handles the computer use subprocess
type Manager struct {
	cmd     *exec.Cmd
	stdin   io.WriteCloser
	stdout  *bufio.Reader
	mu      sync.Mutex
	running bool
}

// Command represents a computer use action
type Command struct {
	Action          string    `json:"action"`
	Coordinate      []int     `json:"coordinate,omitempty"`
	StartCoordinate []int     `json:"start_coordinate,omitempty"`
	Text            string    `json:"text,omitempty"`
	Key             string    `json:"key,omitempty"`
	Direction       string    `json:"direction,omitempty"`
	Amount          int       `json:"amount,omitempty"`
	Duration        float64   `json:"duration,omitempty"`
}

// Result represents a computer use action result
type Result struct {
	Success       bool   `json:"success"`
	Error         string `json:"error,omitempty"`
	Base64Image   string `json:"base64_image,omitempty"`
	DisplayWidth  int    `json:"display_width,omitempty"`
	DisplayHeight int    `json:"display_height,omitempty"`
	ScreenWidth   int    `json:"screen_width,omitempty"`
	ScreenHeight  int    `json:"screen_height,omitempty"`
	Ready         bool   `json:"ready,omitempty"`
}

// Global manager instance
var DefaultManager *Manager

func init() {
	DefaultManager = &Manager{}
}

// Start launches the Python computer use subprocess
func (m *Manager) Start() error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.running {
		return nil
	}

	scriptPath := m.findScript()
	if scriptPath == "" {
		return fmt.Errorf("computer.py script not found")
	}

	// Check for venv Python
	scriptDir := filepath.Dir(scriptPath)
	venvPython := filepath.Join(scriptDir, ".venv", "bin", "python3")
	pythonCmd := "python3"
	if _, err := os.Stat(venvPython); err == nil {
		pythonCmd = venvPython
	}

	log.Printf("Starting computer use subprocess: %s %s", pythonCmd, scriptPath)

	m.cmd = exec.Command(pythonCmd, scriptPath)
	m.cmd.Stderr = os.Stderr

	var err error
	m.stdin, err = m.cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("failed to get stdin: %w", err)
	}

	stdout, err := m.cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("failed to get stdout: %w", err)
	}
	m.stdout = bufio.NewReader(stdout)

	if err := m.cmd.Start(); err != nil {
		return fmt.Errorf("failed to start computer use process: %w", err)
	}

	// Wait for ready signal
	line, err := m.stdout.ReadString('\n')
	if err != nil {
		return fmt.Errorf("failed to read ready signal: %w", err)
	}

	var ready Result
	if err := json.Unmarshal([]byte(line), &ready); err != nil {
		return fmt.Errorf("invalid ready signal: %w", err)
	}

	if !ready.Ready {
		return fmt.Errorf("computer use process not ready")
	}

	m.running = true
	log.Println("Computer use subprocess started")
	return nil
}

// findScript locates the computer.py script
func (m *Manager) findScript() string {
	paths := []string{
		"scripts/computer.py",
		"daemon/scripts/computer.py",
		"../scripts/computer.py",
		"/Users/doddagowtham/Desktop/dungeon/alfred/daemon/scripts/computer.py",
	}

	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		paths = append(paths, filepath.Join(dir, "scripts", "computer.py"))
		paths = append(paths, filepath.Join(dir, "..", "scripts", "computer.py"))
	}

	for _, p := range paths {
		if _, err := os.Stat(p); err == nil {
			abs, _ := filepath.Abs(p)
			return abs
		}
	}

	return ""
}

// Stop stops the computer use subprocess
func (m *Manager) Stop() {
	m.mu.Lock()
	defer m.mu.Unlock()

	if !m.running {
		return
	}

	if m.cmd != nil && m.cmd.Process != nil {
		m.cmd.Process.Kill()
	}

	m.running = false
	log.Println("Computer use subprocess stopped")
}

// Execute runs a computer use action
func (m *Manager) Execute(cmd Command) (*Result, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	// Auto-start if not running
	if !m.running {
		m.mu.Unlock()
		if err := m.Start(); err != nil {
			return nil, err
		}
		m.mu.Lock()
	}

	return m.sendCommand(cmd)
}

// sendCommand sends a command and reads the response
func (m *Manager) sendCommand(cmd Command) (*Result, error) {
	data, err := json.Marshal(cmd)
	if err != nil {
		return nil, fmt.Errorf("failed to encode command: %w", err)
	}

	if _, err := m.stdin.Write(append(data, '\n')); err != nil {
		return nil, fmt.Errorf("failed to send command: %w", err)
	}

	line, err := m.stdout.ReadString('\n')
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	var result Result
	if err := json.Unmarshal([]byte(line), &result); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return &result, nil
}

// ExecuteRaw runs a command from a raw map (for handler integration)
func (m *Manager) ExecuteRaw(params map[string]interface{}) (*Result, error) {
	cmd := Command{}

	if action, ok := params["action"].(string); ok {
		cmd.Action = action
	}
	if text, ok := params["text"].(string); ok {
		cmd.Text = text
	}
	if key, ok := params["key"].(string); ok {
		cmd.Key = key
	}
	if direction, ok := params["direction"].(string); ok {
		cmd.Direction = direction
	}
	if amount, ok := params["amount"].(float64); ok {
		cmd.Amount = int(amount)
	}
	if duration, ok := params["duration"].(float64); ok {
		cmd.Duration = duration
	}

	// Handle coordinate arrays
	if coord, ok := params["coordinate"].([]interface{}); ok && len(coord) >= 2 {
		x, _ := coord[0].(float64)
		y, _ := coord[1].(float64)
		cmd.Coordinate = []int{int(x), int(y)}
	}
	if coord, ok := params["start_coordinate"].([]interface{}); ok && len(coord) >= 2 {
		x, _ := coord[0].(float64)
		y, _ := coord[1].(float64)
		cmd.StartCoordinate = []int{int(x), int(y)}
	}

	return m.Execute(cmd)
}
