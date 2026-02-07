package executor

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

// SelfModification handles operations where Ultron modifies itself
type SelfModification struct {
	executor    *Executor
	ultronRoot  string // Root directory of Ultron installation
	primeRoot   string // Root directory of Prime
	daemonRoot  string // Root directory of Daemon
	backupDir   string // Directory for backups before modifications
}

// NewSelfModification creates a new self-modification handler
func NewSelfModification(ultronRoot string) *SelfModification {
	return &SelfModification{
		executor:   New(),
		ultronRoot: ultronRoot,
		primeRoot:  filepath.Join(ultronRoot, "prime"),
		daemonRoot: filepath.Join(ultronRoot, "daemon"),
		backupDir:  filepath.Join(ultronRoot, ".backups"),
	}
}

// BackupFile creates a backup of a file before modification
func (s *SelfModification) BackupFile(path string) (string, error) {
	// Create backup directory
	timestamp := time.Now().Format("20060102-150405")
	backupPath := filepath.Join(s.backupDir, timestamp, filepath.Base(path))

	if err := os.MkdirAll(filepath.Dir(backupPath), 0755); err != nil {
		return "", fmt.Errorf("failed to create backup dir: %w", err)
	}

	// Read original file
	content, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("failed to read file: %w", err)
	}

	// Write backup
	if err := os.WriteFile(backupPath, content, 0644); err != nil {
		return "", fmt.Errorf("failed to write backup: %w", err)
	}

	return backupPath, nil
}

// ModifyPrimeCode modifies Prime's source code
func (s *SelfModification) ModifyPrimeCode(ctx context.Context, filePath, oldContent, newContent string) error {
	fullPath := filepath.Join(s.primeRoot, filePath)

	// Backup first
	backupPath, err := s.BackupFile(fullPath)
	if err != nil {
		return fmt.Errorf("backup failed: %w", err)
	}

	// Read current content
	content, err := os.ReadFile(fullPath)
	if err != nil {
		return fmt.Errorf("failed to read file: %w", err)
	}

	// Replace content
	newFileContent := strings.Replace(string(content), oldContent, newContent, 1)
	if newFileContent == string(content) {
		return fmt.Errorf("old content not found in file")
	}

	// Write modified content
	if err := os.WriteFile(fullPath, []byte(newFileContent), 0644); err != nil {
		return fmt.Errorf("failed to write file: %w", err)
	}

	fmt.Printf("Modified %s (backup at %s)\n", fullPath, backupPath)
	return nil
}

// ModifyDaemonCode modifies Daemon's source code
func (s *SelfModification) ModifyDaemonCode(ctx context.Context, filePath, oldContent, newContent string) error {
	fullPath := filepath.Join(s.daemonRoot, filePath)

	// Backup first
	backupPath, err := s.BackupFile(fullPath)
	if err != nil {
		return fmt.Errorf("backup failed: %w", err)
	}

	// Read current content
	content, err := os.ReadFile(fullPath)
	if err != nil {
		return fmt.Errorf("failed to read file: %w", err)
	}

	// Replace content
	newFileContent := strings.Replace(string(content), oldContent, newContent, 1)
	if newFileContent == string(content) {
		return fmt.Errorf("old content not found in file")
	}

	// Write modified content
	if err := os.WriteFile(fullPath, []byte(newFileContent), 0644); err != nil {
		return fmt.Errorf("failed to write file: %w", err)
	}

	fmt.Printf("Modified %s (backup at %s)\n", fullPath, backupPath)
	return nil
}

// CreatePrimeFile creates a new file in Prime
func (s *SelfModification) CreatePrimeFile(ctx context.Context, filePath, content string) error {
	fullPath := filepath.Join(s.primeRoot, filePath)

	// Create directories if needed
	if err := os.MkdirAll(filepath.Dir(fullPath), 0755); err != nil {
		return fmt.Errorf("failed to create directories: %w", err)
	}

	// Write file
	if err := os.WriteFile(fullPath, []byte(content), 0644); err != nil {
		return fmt.Errorf("failed to write file: %w", err)
	}

	fmt.Printf("Created %s\n", fullPath)
	return nil
}

// CreateDaemonFile creates a new file in Daemon
func (s *SelfModification) CreateDaemonFile(ctx context.Context, filePath, content string) error {
	fullPath := filepath.Join(s.daemonRoot, filePath)

	// Create directories if needed
	if err := os.MkdirAll(filepath.Dir(fullPath), 0755); err != nil {
		return fmt.Errorf("failed to create directories: %w", err)
	}

	// Write file
	if err := os.WriteFile(fullPath, []byte(content), 0644); err != nil {
		return fmt.Errorf("failed to write file: %w", err)
	}

	fmt.Printf("Created %s\n", fullPath)
	return nil
}

// RebuildDaemon rebuilds the daemon binary
func (s *SelfModification) RebuildDaemon(ctx context.Context) (*ShellResult, error) {
	cmd := "go build -o daemon cmd/daemon/main.go"
	return s.executor.ExecuteShell(ctx, cmd, s.daemonRoot, nil, nil)
}

// RestartPrime restarts the Prime service
func (s *SelfModification) RestartPrime(ctx context.Context) (*ShellResult, error) {
	// This depends on how Prime is run - systemd, supervisor, docker, etc.

	// Try systemd first
	if _, err := exec.LookPath("systemctl"); err == nil {
		result, err := s.executor.ExecuteShell(ctx, "sudo systemctl restart ultron-prime", "", nil, nil)
		if err == nil && result.ExitCode == 0 {
			return result, nil
		}
	}

	// Try docker
	result, err := s.executor.ExecuteShell(ctx, "docker restart ultron-prime", "", nil, nil)
	if err == nil && result.ExitCode == 0 {
		return result, nil
	}

	// Try finding and killing the uvicorn process, then starting it
	// This is more complex and requires the startup command

	return nil, fmt.Errorf("could not determine how to restart Prime")
}

// RestartDaemon restarts the daemon (careful - this restarts itself!)
func (s *SelfModification) RestartDaemon(ctx context.Context) error {
	// Get current executable
	executable, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to get executable: %w", err)
	}

	// Get current arguments
	args := os.Args[1:]

	// Fork a new process
	cmd := exec.Command(executable, args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start new daemon: %w", err)
	}

	// Exit current process after small delay
	go func() {
		time.Sleep(1 * time.Second)
		os.Exit(0)
	}()

	return nil
}

// UpdatePrimeDependencies updates Prime's Python dependencies
func (s *SelfModification) UpdatePrimeDependencies(ctx context.Context) (*ShellResult, error) {
	cmd := "pip install -r requirements.txt --upgrade"
	return s.executor.ExecuteShell(ctx, cmd, s.primeRoot, nil, nil)
}

// UpdateDaemonDependencies updates Daemon's Go dependencies
func (s *SelfModification) UpdateDaemonDependencies(ctx context.Context) (*ShellResult, error) {
	cmd := "go mod tidy && go mod download"
	return s.executor.ExecuteShell(ctx, cmd, s.daemonRoot, nil, nil)
}

// GitPull pulls latest changes from git
func (s *SelfModification) GitPull(ctx context.Context) (*ShellResult, error) {
	return s.executor.ExecuteShell(ctx, "git pull", s.ultronRoot, nil, nil)
}

// GitCommit commits changes
func (s *SelfModification) GitCommit(ctx context.Context, message string) (*ShellResult, error) {
	cmd := fmt.Sprintf("git add -A && git commit -m %q", message)
	return s.executor.ExecuteShell(ctx, cmd, s.ultronRoot, nil, nil)
}

// GitPush pushes changes
func (s *SelfModification) GitPush(ctx context.Context) (*ShellResult, error) {
	return s.executor.ExecuteShell(ctx, "git push", s.ultronRoot, nil, nil)
}

// GetUltronVersion returns current Ultron version info
func (s *SelfModification) GetUltronVersion(ctx context.Context) (map[string]string, error) {
	info := make(map[string]string)

	// Get git info
	gitHash, _ := s.executor.ExecuteShell(ctx, "git rev-parse HEAD", s.ultronRoot, nil, nil)
	if gitHash != nil {
		info["git_commit"] = strings.TrimSpace(gitHash.Stdout)
	}

	gitBranch, _ := s.executor.ExecuteShell(ctx, "git branch --show-current", s.ultronRoot, nil, nil)
	if gitBranch != nil {
		info["git_branch"] = strings.TrimSpace(gitBranch.Stdout)
	}

	// Get Go version
	info["go_version"] = runtime.Version()
	info["go_os"] = runtime.GOOS
	info["go_arch"] = runtime.GOARCH

	return info, nil
}

// ListBackups lists available backups
func (s *SelfModification) ListBackups(ctx context.Context) ([]string, error) {
	var backups []string

	entries, err := os.ReadDir(s.backupDir)
	if err != nil {
		if os.IsNotExist(err) {
			return backups, nil
		}
		return nil, err
	}

	for _, entry := range entries {
		if entry.IsDir() {
			backups = append(backups, entry.Name())
		}
	}

	return backups, nil
}

// RestoreBackup restores from a backup
func (s *SelfModification) RestoreBackup(ctx context.Context, backupName, targetPath string) error {
	backupPath := filepath.Join(s.backupDir, backupName)

	// Walk backup directory and restore files
	return filepath.Walk(backupPath, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}

		if info.IsDir() {
			return nil
		}

		// Calculate relative path
		relPath, _ := filepath.Rel(backupPath, path)
		destPath := filepath.Join(targetPath, relPath)

		// Read backup file
		content, err := os.ReadFile(path)
		if err != nil {
			return err
		}

		// Ensure directory exists
		os.MkdirAll(filepath.Dir(destPath), 0755)

		// Write to destination
		return os.WriteFile(destPath, content, 0644)
	})
}

// AddCapability adds a new capability to the daemon dynamically
func (s *SelfModification) AddCapability(ctx context.Context, name, description, code string) error {
	// This would generate new Go code for a capability
	// For now, we'll create a plugin-like structure

	pluginDir := filepath.Join(s.daemonRoot, "plugins", name)
	if err := os.MkdirAll(pluginDir, 0755); err != nil {
		return err
	}

	// Write capability code
	pluginFile := filepath.Join(pluginDir, "plugin.go")
	return os.WriteFile(pluginFile, []byte(code), 0644)
}
