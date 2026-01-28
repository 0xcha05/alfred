package session

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// Manager handles tmux session lifecycle
type Manager struct {
	mu       sync.RWMutex
	sessions map[string]*Session
	logDir   string
}

// Session represents a tmux session
type Session struct {
	ID          string
	Name        string
	Command     string
	WorkingDir  string
	CreatedAt   time.Time
	IsRunning   bool
	LogFile     string
	lastChecked time.Time
}

// NewManager creates a new session manager
func NewManager() *Manager {
	logDir := filepath.Join(os.TempDir(), "alfred-sessions")
	os.MkdirAll(logDir, 0755)

	return &Manager{
		sessions: make(map[string]*Session),
		logDir:   logDir,
	}
}

// Create creates a new tmux session
func (m *Manager) Create(name, command, workingDir string) (*Session, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	// Generate session ID
	sessionID := fmt.Sprintf("alfred-%s-%d", name, time.Now().UnixNano())

	// Log file for capturing output
	logFile := filepath.Join(m.logDir, sessionID+".log")

	// Build tmux command
	var tmuxCmd *exec.Cmd
	if command != "" {
		// Create session with initial command
		tmuxCmd = exec.Command("tmux", "new-session", "-d", "-s", sessionID, "-c", workingDir, command)
	} else {
		// Create session with shell
		tmuxCmd = exec.Command("tmux", "new-session", "-d", "-s", sessionID, "-c", workingDir)
	}

	if workingDir == "" {
		workingDir, _ = os.Getwd()
	}
	tmuxCmd.Dir = workingDir

	if err := tmuxCmd.Run(); err != nil {
		return nil, fmt.Errorf("failed to create tmux session: %w", err)
	}

	// Enable logging
	pipeReadCmd := exec.Command("tmux", "pipe-pane", "-t", sessionID, fmt.Sprintf("cat >> %s", logFile))
	pipeReadCmd.Run()

	session := &Session{
		ID:          sessionID,
		Name:        name,
		Command:     command,
		WorkingDir:  workingDir,
		CreatedAt:   time.Now(),
		IsRunning:   true,
		LogFile:     logFile,
		lastChecked: time.Now(),
	}

	m.sessions[sessionID] = session
	return session, nil
}

// Get returns a session by ID
func (m *Manager) Get(sessionID string) (*Session, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	session, ok := m.sessions[sessionID]
	return session, ok
}

// List returns all sessions
func (m *Manager) List() []*Session {
	m.mu.RLock()
	defer m.mu.RUnlock()

	// Also check for tmux sessions not in our map
	m.refreshFromTmux()

	sessions := make([]*Session, 0, len(m.sessions))
	for _, s := range m.sessions {
		sessions = append(sessions, s)
	}
	return sessions
}

// refreshFromTmux syncs our session list with actual tmux sessions
func (m *Manager) refreshFromTmux() {
	cmd := exec.Command("tmux", "list-sessions", "-F", "#{session_name}")
	output, err := cmd.Output()
	if err != nil {
		return // tmux not running or no sessions
	}

	activeSessions := make(map[string]bool)
	for _, line := range strings.Split(string(output), "\n") {
		line = strings.TrimSpace(line)
		if line != "" && strings.HasPrefix(line, "alfred-") {
			activeSessions[line] = true
		}
	}

	// Mark sessions as not running if they're gone
	for id, session := range m.sessions {
		if !activeSessions[id] {
			session.IsRunning = false
		}
	}
}

// SendCommand sends a command to a session
func (m *Manager) SendCommand(sessionID, command string) error {
	m.mu.RLock()
	session, ok := m.sessions[sessionID]
	m.mu.RUnlock()

	if !ok {
		return fmt.Errorf("session not found: %s", sessionID)
	}

	if !session.IsRunning {
		return fmt.Errorf("session is not running: %s", sessionID)
	}

	// Send keys to tmux session
	cmd := exec.Command("tmux", "send-keys", "-t", sessionID, command, "Enter")
	return cmd.Run()
}

// GetOutput returns the current output from a session's log file
func (m *Manager) GetOutput(sessionID string, follow bool) (<-chan string, error) {
	m.mu.RLock()
	session, ok := m.sessions[sessionID]
	m.mu.RUnlock()

	if !ok {
		return nil, fmt.Errorf("session not found: %s", sessionID)
	}

	output := make(chan string, 100)

	go func() {
		defer close(output)

		file, err := os.Open(session.LogFile)
		if err != nil {
			output <- fmt.Sprintf("[Error opening log: %v]", err)
			return
		}
		defer file.Close()

		scanner := bufio.NewScanner(file)
		for scanner.Scan() {
			output <- scanner.Text()
		}

		if !follow {
			return
		}

		// Follow mode - watch for new content
		ticker := time.NewTicker(100 * time.Millisecond)
		defer ticker.Stop()

		for range ticker.C {
			for scanner.Scan() {
				output <- scanner.Text()
			}

			// Check if session is still running
			m.mu.RLock()
			running := session.IsRunning
			m.mu.RUnlock()

			if !running {
				return
			}
		}
	}()

	return output, nil
}

// Kill terminates a session
func (m *Manager) Kill(sessionID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	session, ok := m.sessions[sessionID]
	if !ok {
		return fmt.Errorf("session not found: %s", sessionID)
	}

	// Kill tmux session
	cmd := exec.Command("tmux", "kill-session", "-t", sessionID)
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("failed to kill session: %w", err)
	}

	session.IsRunning = false

	// Optionally clean up log file
	os.Remove(session.LogFile)

	return nil
}

// RunInSession runs a command in a session and waits for completion
func (m *Manager) RunInSession(ctx context.Context, sessionID, command string, output chan<- string) (int, error) {
	m.mu.RLock()
	session, ok := m.sessions[sessionID]
	m.mu.RUnlock()

	if !ok {
		return -1, fmt.Errorf("session not found: %s", sessionID)
	}

	// Send command
	if err := m.SendCommand(sessionID, command); err != nil {
		return -1, err
	}

	// Stream output
	outputChan, err := m.GetOutput(sessionID, true)
	if err != nil {
		return -1, err
	}

	// Forward output
	for {
		select {
		case <-ctx.Done():
			return -1, ctx.Err()
		case line, ok := <-outputChan:
			if !ok {
				return 0, nil
			}
			if output != nil {
				select {
				case output <- line:
				case <-ctx.Done():
					return -1, ctx.Err()
				}
			}
		}
	}
}

// Cleanup removes stale sessions
func (m *Manager) Cleanup() {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.refreshFromTmux()

	// Remove sessions that are no longer running and older than 1 hour
	cutoff := time.Now().Add(-1 * time.Hour)
	for id, session := range m.sessions {
		if !session.IsRunning && session.CreatedAt.Before(cutoff) {
			os.Remove(session.LogFile)
			delete(m.sessions, id)
		}
	}
}
