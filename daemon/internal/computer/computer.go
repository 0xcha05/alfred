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
	Success         bool    `json:"success"`
	Error           string  `json:"error,omitempty"`
	Base64Image     string  `json:"base64_image,omitempty"`
	DisplayWidth    int     `json:"display_width,omitempty"`
	DisplayHeight   int     `json:"display_height,omitempty"`
	ScreenWidth     int     `json:"screen_width,omitempty"`
	ScreenHeight    int     `json:"screen_height,omitempty"`
	ApiWidth        int     `json:"api_width,omitempty"`
	ApiHeight       int     `json:"api_height,omitempty"`
	ScaleX          float64 `json:"scale_x,omitempty"`
	ScaleY          float64 `json:"scale_y,omitempty"`
	ScreenshotError string  `json:"screenshot_error,omitempty"`
	HasCliclick     bool    `json:"has_cliclick,omitempty"`
	Ready           bool    `json:"ready,omitempty"`
	X               int     `json:"x,omitempty"`
	Y               int     `json:"y,omitempty"`
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
		"/Users/doddagowtham/Desktop/dungeon/ultron/daemon/scripts/computer.py",
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

// ExecuteRaw runs a command from a raw map (for handler integration).
// Instead of mapping individual fields, we forward the entire params map
// as JSON to the Python subprocess. This ensures ALL Anthropic fields
// (action, text, coordinate, scroll_direction, scroll_amount, etc.)
// are passed through without needing Go struct mapping.
func (m *Manager) ExecuteRaw(params map[string]interface{}) (*Result, error) {
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

	// Marshal the raw params directly - Python handles all field parsing
	data, err := json.Marshal(params)
	if err != nil {
		return nil, fmt.Errorf("failed to encode params: %w", err)
	}

	log.Printf("[computer] Sending raw params: action=%v", params["action"])

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
