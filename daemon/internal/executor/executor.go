package executor

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// Executor handles command execution and file operations
type Executor struct {
	sessions sync.Map // session name -> *Session
}

// Session represents a persistent shell session
type Session struct {
	Name      string
	Command   string
	CreatedAt time.Time
	cmd       *exec.Cmd
	stdin     io.WriteCloser
	stdout    io.ReadCloser
	stderr    io.ReadCloser
}

// New creates a new Executor
func New() *Executor {
	return &Executor{}
}

// ShellResult holds the result of a shell command
type ShellResult struct {
	Stdout   string
	Stderr   string
	ExitCode int
	Error    error
}

// ExecuteShell executes a shell command and streams output
func (e *Executor) ExecuteShell(ctx context.Context, command, workDir string, env map[string]string, outputChan chan<- string) (*ShellResult, error) {
	// Create command
	cmd := exec.CommandContext(ctx, "sh", "-c", command)

	if workDir != "" {
		cmd.Dir = workDir
	}

	// Set environment
	cmd.Env = os.Environ()
	for k, v := range env {
		cmd.Env = append(cmd.Env, fmt.Sprintf("%s=%s", k, v))
	}

	// Get stdout and stderr pipes
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("failed to get stdout pipe: %w", err)
	}

	stderr, err := cmd.StderrPipe()
	if err != nil {
		return nil, fmt.Errorf("failed to get stderr pipe: %w", err)
	}

	// Start command
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("failed to start command: %w", err)
	}

	var stdoutBuf, stderrBuf strings.Builder
	var wg sync.WaitGroup

	// Stream stdout
	wg.Add(1)
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			line := scanner.Text()
			stdoutBuf.WriteString(line + "\n")
			if outputChan != nil {
				select {
				case outputChan <- line:
				case <-ctx.Done():
					return
				}
			}
		}
	}()

	// Stream stderr
	wg.Add(1)
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stderr)
		for scanner.Scan() {
			line := scanner.Text()
			stderrBuf.WriteString(line + "\n")
			if outputChan != nil {
				select {
				case outputChan <- "[stderr] " + line:
				case <-ctx.Done():
					return
				}
			}
		}
	}()

	// Wait for output streams to finish
	wg.Wait()

	// Wait for command to complete
	err = cmd.Wait()

	result := &ShellResult{
		Stdout:   stdoutBuf.String(),
		Stderr:   stderrBuf.String(),
		ExitCode: 0,
	}

	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			result.ExitCode = exitErr.ExitCode()
		} else {
			result.Error = err
		}
	}

	return result, nil
}

// ReadFile reads a file's contents (simple version)
func (e *Executor) ReadFile(path string) ([]byte, error) {
	content, _, err := e.ReadFileWithOffsets(path, 0, 0)
	return content, err
}

// ReadFileWithOffsets reads a file's contents with offset and limit
func (e *Executor) ReadFileWithOffsets(path string, offset, limit int64) ([]byte, int64, error) {
	// Resolve path
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, 0, fmt.Errorf("invalid path: %w", err)
	}

	// Open file
	file, err := os.Open(absPath)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to open file: %w", err)
	}
	defer file.Close()

	// Get file info
	info, err := file.Stat()
	if err != nil {
		return nil, 0, fmt.Errorf("failed to stat file: %w", err)
	}

	size := info.Size()

	// Seek to offset if specified
	if offset > 0 {
		if _, err := file.Seek(offset, 0); err != nil {
			return nil, 0, fmt.Errorf("failed to seek: %w", err)
		}
	}

	// Determine read size
	readSize := size - offset
	if limit > 0 && limit < readSize {
		readSize = limit
	}

	// Read content
	content := make([]byte, readSize)
	n, err := io.ReadFull(file, content)
	if err != nil && err != io.EOF && err != io.ErrUnexpectedEOF {
		return nil, 0, fmt.Errorf("failed to read file: %w", err)
	}

	return content[:n], size, nil
}

// WriteFile writes content to a file
func (e *Executor) WriteFile(path string, content []byte, createDirs bool, mode os.FileMode) error {
	// Resolve path
	absPath, err := filepath.Abs(path)
	if err != nil {
		return fmt.Errorf("invalid path: %w", err)
	}

	// Create directories if needed
	if createDirs {
		dir := filepath.Dir(absPath)
		if err := os.MkdirAll(dir, 0755); err != nil {
			return fmt.Errorf("failed to create directories: %w", err)
		}
	}

	// Set default mode
	if mode == 0 {
		mode = 0644
	}

	// Write file
	if err := os.WriteFile(absPath, content, mode); err != nil {
		return fmt.Errorf("failed to write file: %w", err)
	}

	return nil
}

// ListFiles lists files in a directory (simple version)
func (e *Executor) ListFiles(path string, recursive bool) ([]FileInfo, error) {
	return e.ListFilesWithPattern(path, recursive, "")
}

// ListFilesWithPattern lists files in a directory with pattern matching
func (e *Executor) ListFilesWithPattern(path string, recursive bool, pattern string) ([]FileInfo, error) {
	// Resolve path
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, fmt.Errorf("invalid path: %w", err)
	}

	var files []FileInfo

	walkFn := func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return nil // Skip files we can't access
		}

		// Skip hidden files and directories
		if strings.HasPrefix(info.Name(), ".") && p != absPath {
			if info.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}

		// Match pattern if specified
		if pattern != "" {
			matched, _ := filepath.Match(pattern, info.Name())
			if !matched {
				return nil
			}
		}

		files = append(files, FileInfo{
			Name:        info.Name(),
			Path:        p,
			Size:        info.Size(),
			IsDirectory: info.IsDir(),
			IsDir:       info.IsDir(),
			ModifiedAt:  info.ModTime(),
			ModTime:     info.ModTime(),
			Mode:        info.Mode(),
		})

		// Don't recurse if not requested
		if !recursive && info.IsDir() && p != absPath {
			return filepath.SkipDir
		}

		return nil
	}

	if err := filepath.Walk(absPath, walkFn); err != nil {
		return nil, fmt.Errorf("failed to list files: %w", err)
	}

	return files, nil
}

// FileInfo holds file metadata
type FileInfo struct {
	Name        string
	Path        string
	Size        int64
	IsDirectory bool
	IsDir       bool // Alias for IsDirectory
	ModifiedAt  time.Time
	ModTime     time.Time // Alias for ModifiedAt
	Mode        os.FileMode
}
