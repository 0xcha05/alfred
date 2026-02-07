// Package browser provides Playwright-based browser automation.
// It communicates with a Python subprocess that runs the actual Playwright commands.
package browser

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

// Manager handles the browser subprocess
type Manager struct {
	cmd       *exec.Cmd
	stdin     io.WriteCloser
	stdout    *bufio.Reader
	mu        sync.Mutex
	running   bool
	scriptDir string
}

// Command represents a browser command
type Command struct {
	Action        string `json:"action"`
	URL           string `json:"url,omitempty"`
	Selector      string `json:"selector,omitempty"`
	Text          string `json:"text,omitempty"`
	Script        string `json:"script,omitempty"`
	Path          string `json:"path,omitempty"`
	Headless      bool   `json:"headless,omitempty"`
	UseRealChrome bool   `json:"use_real_chrome,omitempty"`
	FullPage      bool   `json:"full_page,omitempty"`
	Timeout       int    `json:"timeout,omitempty"`
	Amount        int    `json:"amount,omitempty"`
	Direction     string `json:"direction,omitempty"`
}

// Result represents a browser command result
type Result struct {
	Success  bool        `json:"success"`
	Error    string      `json:"error,omitempty"`
	Message  string      `json:"message,omitempty"`
	URL      string      `json:"url,omitempty"`
	Title    string      `json:"title,omitempty"`
	Text     string      `json:"text,omitempty"`
	Content  string      `json:"content,omitempty"`
	Path     string      `json:"path,omitempty"`
	Elements []string    `json:"elements,omitempty"`
	Count    int         `json:"count,omitempty"`
	Result   interface{} `json:"result,omitempty"`
	Ready    bool        `json:"ready,omitempty"`
}

// Global manager instance
var DefaultManager *Manager

func init() {
	DefaultManager = &Manager{}
}

// Start launches the Python browser subprocess
func (m *Manager) Start() error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.running {
		return nil
	}

	// Find the script
	scriptPath := m.findScript()
	if scriptPath == "" {
		return fmt.Errorf("browser.py script not found")
	}

	// Check for venv Python
	scriptDir := filepath.Dir(scriptPath)
	venvPython := filepath.Join(scriptDir, ".venv", "bin", "python3")
	pythonCmd := "python3"
	if _, err := os.Stat(venvPython); err == nil {
		pythonCmd = venvPython
	}

	log.Printf("Starting browser subprocess: %s %s", pythonCmd, scriptPath)

	// Start the Python subprocess
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
		return fmt.Errorf("failed to start browser process: %w", err)
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
		return fmt.Errorf("browser process not ready")
	}

	m.running = true
	log.Println("Browser subprocess started")
	return nil
}

// findScript locates the browser.py script
func (m *Manager) findScript() string {
	// Try common locations
	paths := []string{
		"scripts/browser.py",
		"daemon/scripts/browser.py",
		"../scripts/browser.py",
		"/Users/doddagowtham/Desktop/dungeon/ultron/daemon/scripts/browser.py",
	}

	// Also try relative to executable
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		paths = append(paths, filepath.Join(dir, "scripts", "browser.py"))
		paths = append(paths, filepath.Join(dir, "..", "scripts", "browser.py"))
	}

	for _, p := range paths {
		if _, err := os.Stat(p); err == nil {
			abs, _ := filepath.Abs(p)
			return abs
		}
	}

	return ""
}

// Stop stops the browser subprocess
func (m *Manager) Stop() {
	m.mu.Lock()
	defer m.mu.Unlock()

	if !m.running {
		return
	}

	// Send close command
	m.sendCommand(Command{Action: "close"})

	if m.cmd != nil && m.cmd.Process != nil {
		m.cmd.Process.Kill()
	}

	m.running = false
	log.Println("Browser subprocess stopped")
}

// Execute runs a browser command
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
	// Encode and send
	data, err := json.Marshal(cmd)
	if err != nil {
		return nil, fmt.Errorf("failed to encode command: %w", err)
	}

	if _, err := m.stdin.Write(append(data, '\n')); err != nil {
		return nil, fmt.Errorf("failed to send command: %w", err)
	}

	// Read response
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

// Convenience methods

// Launch starts the browser
func (m *Manager) Launch(headless bool) (*Result, error) {
	return m.Execute(Command{Action: "launch", Headless: headless})
}

// Goto navigates to a URL
func (m *Manager) Goto(url string) (*Result, error) {
	return m.Execute(Command{Action: "goto", URL: url})
}

// Click clicks an element
func (m *Manager) Click(selector string) (*Result, error) {
	return m.Execute(Command{Action: "click", Selector: selector})
}

// Type types text into an element
func (m *Manager) Type(selector, text string) (*Result, error) {
	return m.Execute(Command{Action: "type", Selector: selector, Text: text})
}

// GetText gets text from an element
func (m *Manager) GetText(selector string) (*Result, error) {
	return m.Execute(Command{Action: "get_text", Selector: selector})
}

// GetContent gets the page content
func (m *Manager) GetContent() (*Result, error) {
	return m.Execute(Command{Action: "get_content"})
}

// Screenshot takes a screenshot
func (m *Manager) Screenshot(path string, fullPage bool) (*Result, error) {
	return m.Execute(Command{Action: "screenshot", Path: path, FullPage: fullPage})
}

// Evaluate runs JavaScript
func (m *Manager) Evaluate(script string) (*Result, error) {
	return m.Execute(Command{Action: "evaluate", Script: script})
}

// Wait waits for a selector
func (m *Manager) Wait(selector string, timeout int) (*Result, error) {
	return m.Execute(Command{Action: "wait", Selector: selector, Timeout: timeout})
}

// Close closes the browser
func (m *Manager) Close() (*Result, error) {
	return m.Execute(Command{Action: "close"})
}
