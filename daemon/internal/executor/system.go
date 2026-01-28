package executor

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"os/user"
	"runtime"
	"strings"
	"syscall"
)

// SystemInfo returns comprehensive system information
type SystemInfo struct {
	Hostname     string
	OS           string
	Arch         string
	NumCPU       int
	Username     string
	HomeDir      string
	WorkingDir   string
	PID          int
	UID          int
	GID          int
	Environment  map[string]string
	DiskUsage    map[string]DiskUsage
	MemoryInfo   MemoryInfo
	NetworkAddrs []string
}

type DiskUsage struct {
	Total     uint64
	Used      uint64
	Available uint64
	Percent   float64
}

type MemoryInfo struct {
	Total     uint64
	Used      uint64
	Available uint64
	Percent   float64
}

// GetSystemInfo returns detailed system information
func (e *Executor) GetSystemInfo() (*SystemInfo, error) {
	hostname, _ := os.Hostname()
	currentUser, _ := user.Current()
	wd, _ := os.Getwd()

	info := &SystemInfo{
		Hostname:    hostname,
		OS:          runtime.GOOS,
		Arch:        runtime.GOARCH,
		NumCPU:      runtime.NumCPU(),
		WorkingDir:  wd,
		PID:         os.Getpid(),
		Environment: make(map[string]string),
	}

	if currentUser != nil {
		info.Username = currentUser.Username
		info.HomeDir = currentUser.HomeDir
	}

	// Get environment variables
	for _, env := range os.Environ() {
		parts := strings.SplitN(env, "=", 2)
		if len(parts) == 2 {
			// Skip sensitive variables
			key := strings.ToLower(parts[0])
			if !strings.Contains(key, "password") &&
				!strings.Contains(key, "secret") &&
				!strings.Contains(key, "token") &&
				!strings.Contains(key, "api_key") {
				info.Environment[parts[0]] = parts[1]
			}
		}
	}

	return info, nil
}

// RunAsRoot runs a command with sudo if available
func (e *Executor) RunAsRoot(ctx context.Context, command string) (*ShellResult, error) {
	// Check if already root
	if os.Getuid() == 0 {
		return e.ExecuteShell(ctx, command, "", nil, nil)
	}

	// Use sudo
	sudoCmd := fmt.Sprintf("sudo -n %s", command)
	return e.ExecuteShell(ctx, sudoCmd, "", nil, nil)
}

// InstallPackage installs a package using the system package manager
func (e *Executor) InstallPackage(ctx context.Context, packages []string) (*ShellResult, error) {
	var cmd string

	switch runtime.GOOS {
	case "darwin":
		cmd = fmt.Sprintf("brew install %s", strings.Join(packages, " "))
	case "linux":
		// Detect package manager
		if _, err := exec.LookPath("apt-get"); err == nil {
			cmd = fmt.Sprintf("sudo apt-get install -y %s", strings.Join(packages, " "))
		} else if _, err := exec.LookPath("yum"); err == nil {
			cmd = fmt.Sprintf("sudo yum install -y %s", strings.Join(packages, " "))
		} else if _, err := exec.LookPath("pacman"); err == nil {
			cmd = fmt.Sprintf("sudo pacman -S --noconfirm %s", strings.Join(packages, " "))
		} else {
			return nil, fmt.Errorf("no supported package manager found")
		}
	default:
		return nil, fmt.Errorf("unsupported OS: %s", runtime.GOOS)
	}

	return e.ExecuteShell(ctx, cmd, "", nil, nil)
}

// ManageService manages system services (start, stop, restart, status)
func (e *Executor) ManageService(ctx context.Context, service, action string) (*ShellResult, error) {
	var cmd string

	switch runtime.GOOS {
	case "darwin":
		switch action {
		case "start":
			cmd = fmt.Sprintf("launchctl start %s", service)
		case "stop":
			cmd = fmt.Sprintf("launchctl stop %s", service)
		case "restart":
			cmd = fmt.Sprintf("launchctl stop %s && launchctl start %s", service, service)
		case "status":
			cmd = fmt.Sprintf("launchctl list | grep %s", service)
		default:
			return nil, fmt.Errorf("unsupported action: %s", action)
		}
	case "linux":
		if _, err := exec.LookPath("systemctl"); err == nil {
			cmd = fmt.Sprintf("sudo systemctl %s %s", action, service)
		} else {
			cmd = fmt.Sprintf("sudo service %s %s", service, action)
		}
	default:
		return nil, fmt.Errorf("unsupported OS: %s", runtime.GOOS)
	}

	return e.ExecuteShell(ctx, cmd, "", nil, nil)
}

// ManageDocker provides Docker operations
func (e *Executor) ManageDocker(ctx context.Context, args ...string) (*ShellResult, error) {
	cmd := fmt.Sprintf("docker %s", strings.Join(args, " "))
	return e.ExecuteShell(ctx, cmd, "", nil, nil)
}

// ManageProcess provides process management
func (e *Executor) KillProcess(ctx context.Context, pid int, signal syscall.Signal) error {
	process, err := os.FindProcess(pid)
	if err != nil {
		return err
	}
	return process.Signal(signal)
}

// GetProcessList returns list of running processes
func (e *Executor) GetProcessList(ctx context.Context) (*ShellResult, error) {
	var cmd string
	switch runtime.GOOS {
	case "darwin", "linux":
		cmd = "ps aux"
	default:
		cmd = "tasklist"
	}
	return e.ExecuteShell(ctx, cmd, "", nil, nil)
}

// NetworkOperation performs network operations
func (e *Executor) NetworkOperation(ctx context.Context, operation string, args ...string) (*ShellResult, error) {
	var cmd string

	switch operation {
	case "interfaces":
		if runtime.GOOS == "darwin" {
			cmd = "ifconfig"
		} else {
			cmd = "ip addr"
		}
	case "connections":
		cmd = "netstat -an"
	case "ports":
		cmd = "lsof -i -P -n"
	case "ping":
		if len(args) > 0 {
			cmd = fmt.Sprintf("ping -c 4 %s", args[0])
		}
	case "curl":
		cmd = fmt.Sprintf("curl %s", strings.Join(args, " "))
	case "wget":
		cmd = fmt.Sprintf("wget %s", strings.Join(args, " "))
	default:
		return nil, fmt.Errorf("unknown operation: %s", operation)
	}

	return e.ExecuteShell(ctx, cmd, "", nil, nil)
}

// GitOperation performs git operations
func (e *Executor) GitOperation(ctx context.Context, workDir string, args ...string) (*ShellResult, error) {
	cmd := fmt.Sprintf("git %s", strings.Join(args, " "))
	return e.ExecuteShell(ctx, cmd, workDir, nil, nil)
}

// PythonOperation runs Python commands
func (e *Executor) PythonOperation(ctx context.Context, workDir, script string) (*ShellResult, error) {
	// Try python3 first, then python
	pythonCmd := "python3"
	if _, err := exec.LookPath("python3"); err != nil {
		pythonCmd = "python"
	}

	cmd := fmt.Sprintf("%s -c %q", pythonCmd, script)
	return e.ExecuteShell(ctx, cmd, workDir, nil, nil)
}

// PipInstall installs Python packages
func (e *Executor) PipInstall(ctx context.Context, packages []string) (*ShellResult, error) {
	pipCmd := "pip3"
	if _, err := exec.LookPath("pip3"); err != nil {
		pipCmd = "pip"
	}

	cmd := fmt.Sprintf("%s install %s", pipCmd, strings.Join(packages, " "))
	return e.ExecuteShell(ctx, cmd, "", nil, nil)
}

// NodeOperation runs Node.js commands
func (e *Executor) NodeOperation(ctx context.Context, workDir, script string) (*ShellResult, error) {
	cmd := fmt.Sprintf("node -e %q", script)
	return e.ExecuteShell(ctx, cmd, workDir, nil, nil)
}

// NpmInstall runs npm install
func (e *Executor) NpmOperation(ctx context.Context, workDir string, args ...string) (*ShellResult, error) {
	cmd := fmt.Sprintf("npm %s", strings.Join(args, " "))
	return e.ExecuteShell(ctx, cmd, workDir, nil, nil)
}

// Cron manages cron jobs
func (e *Executor) CronOperation(ctx context.Context, operation string, args ...string) (*ShellResult, error) {
	switch operation {
	case "list":
		return e.ExecuteShell(ctx, "crontab -l", "", nil, nil)
	case "add":
		if len(args) < 1 {
			return nil, fmt.Errorf("cron entry required")
		}
		cmd := fmt.Sprintf("(crontab -l 2>/dev/null; echo %q) | crontab -", args[0])
		return e.ExecuteShell(ctx, cmd, "", nil, nil)
	case "remove":
		if len(args) < 1 {
			return nil, fmt.Errorf("pattern required")
		}
		cmd := fmt.Sprintf("crontab -l | grep -v %q | crontab -", args[0])
		return e.ExecuteShell(ctx, cmd, "", nil, nil)
	default:
		return nil, fmt.Errorf("unknown cron operation: %s", operation)
	}
}

// EnvironmentSet sets environment variables for future commands
func (e *Executor) EnvironmentSet(key, value string) {
	os.Setenv(key, value)
}

// EnvironmentGet gets an environment variable
func (e *Executor) EnvironmentGet(key string) string {
	return os.Getenv(key)
}

// ChangeDirectory changes the working directory
func (e *Executor) ChangeDirectory(path string) error {
	return os.Chdir(path)
}
