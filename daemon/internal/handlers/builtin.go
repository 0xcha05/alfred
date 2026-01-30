// Package handlers - built-in command handlers.
// These are the default handlers that ship with the daemon.
// You can add more by calling handlers.Register().
package handlers

import (
	"context"
	"fmt"
	"io/ioutil"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"
)

// RegisterBuiltins registers all built-in command handlers.
func RegisterBuiltins() {
	// Core commands
	Register("ping", handlePing)
	Register("shell", handleShell)
	Register("read_file", handleReadFile)
	Register("write_file", handleWriteFile)
	Register("delete_file", handleDeleteFile)
	Register("list_files", handleListFiles)
	Register("system_info", handleSystemInfo)

	// Process management
	Register("list_processes", handleListProcesses)
	Register("kill_process", handleKillProcess)

	// Docker
	Register("docker", handleDocker)

	// Git
	Register("git", handleGit)

	// Service management
	Register("manage_service", handleManageService)

	// Generic exec - runs any command
	Register("exec", handleExec)
}

func handlePing(params map[string]interface{}) map[string]interface{} {
	return map[string]interface{}{
		"success": true,
		"output":  "pong",
		"time":    time.Now().UTC().Format(time.RFC3339),
	}
}

func handleShell(params map[string]interface{}) map[string]interface{} {
	command, _ := params["command"].(string)
	workDir, _ := params["working_directory"].(string)
	useSudo, _ := params["use_sudo"].(bool)
	timeoutSec, _ := params["timeout"].(float64)

	if command == "" {
		return map[string]interface{}{
			"success": false,
			"error":   "no command provided",
		}
	}

	if useSudo {
		command = "sudo " + command
	}

	if timeoutSec == 0 {
		timeoutSec = 60
	}

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeoutSec)*time.Second)
	defer cancel()

	var cmd *exec.Cmd
	if runtime.GOOS == "windows" {
		cmd = exec.CommandContext(ctx, "cmd", "/C", command)
	} else {
		cmd = exec.CommandContext(ctx, "sh", "-c", command)
	}

	if workDir != "" {
		cmd.Dir = workDir
	}

	output, err := cmd.CombinedOutput()

	result := map[string]interface{}{
		"success":   err == nil,
		"output":    string(output),
		"exit_code": 0,
	}

	if err != nil {
		result["error"] = err.Error()
		if exitErr, ok := err.(*exec.ExitError); ok {
			result["exit_code"] = exitErr.ExitCode()
		}
	}

	return result
}

func handleExec(params map[string]interface{}) map[string]interface{} {
	// Generic exec - just calls shell
	return handleShell(params)
}

func handleReadFile(params map[string]interface{}) map[string]interface{} {
	path, _ := params["path"].(string)
	offset, _ := params["offset"].(float64)
	limit, _ := params["limit"].(float64)

	if path == "" {
		return map[string]interface{}{
			"success": false,
			"error":   "no path provided",
		}
	}

	content, err := ioutil.ReadFile(path)
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	// Handle offset and limit
	lines := strings.Split(string(content), "\n")
	start := int(offset)
	end := len(lines)

	if limit > 0 {
		end = start + int(limit)
		if end > len(lines) {
			end = len(lines)
		}
	}

	if start > 0 || limit > 0 {
		if start < len(lines) {
			lines = lines[start:end]
		} else {
			lines = []string{}
		}
		content = []byte(strings.Join(lines, "\n"))
	}

	return map[string]interface{}{
		"success":     true,
		"content":     string(content),
		"size":        len(content),
		"total_lines": len(strings.Split(string(content), "\n")),
	}
}

func handleWriteFile(params map[string]interface{}) map[string]interface{} {
	path, _ := params["path"].(string)
	content, _ := params["content"].(string)
	appendMode, _ := params["append"].(bool)
	mode, _ := params["mode"].(float64)

	if path == "" {
		return map[string]interface{}{
			"success": false,
			"error":   "no path provided",
		}
	}

	var fileMode os.FileMode = 0644
	if mode > 0 {
		fileMode = os.FileMode(int(mode))
	}

	var err error
	if appendMode {
		f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, fileMode)
		if err == nil {
			_, err = f.WriteString(content)
			f.Close()
		}
	} else {
		err = ioutil.WriteFile(path, []byte(content), fileMode)
	}

	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success": true,
		"path":    path,
		"size":    len(content),
	}
}

func handleDeleteFile(params map[string]interface{}) map[string]interface{} {
	path, _ := params["path"].(string)
	recursive, _ := params["recursive"].(bool)

	if path == "" {
		return map[string]interface{}{
			"success": false,
			"error":   "no path provided",
		}
	}

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
		"path":    path,
	}
}

func handleListFiles(params map[string]interface{}) map[string]interface{} {
	path, _ := params["path"].(string)
	recursive, _ := params["recursive"].(bool)
	pattern, _ := params["pattern"].(string)

	if path == "" {
		path = "."
	}

	var files []map[string]interface{}

	if recursive {
		filepath.Walk(path, func(p string, info os.FileInfo, err error) error {
			if err != nil {
				return nil
			}
			if pattern != "" {
				if matched, _ := filepath.Match(pattern, info.Name()); !matched {
					return nil
				}
			}
			files = append(files, fileToMap(p, info))
			return nil
		})
	} else {
		entries, err := ioutil.ReadDir(path)
		if err != nil {
			return map[string]interface{}{
				"success": false,
				"error":   err.Error(),
			}
		}
		for _, entry := range entries {
			if pattern != "" {
				if matched, _ := filepath.Match(pattern, entry.Name()); !matched {
					continue
				}
			}
			files = append(files, fileToMap(filepath.Join(path, entry.Name()), entry))
		}
	}

	return map[string]interface{}{
		"success": true,
		"files":   files,
		"count":   len(files),
	}
}

func fileToMap(path string, info os.FileInfo) map[string]interface{} {
	return map[string]interface{}{
		"name":     info.Name(),
		"path":     path,
		"size":     info.Size(),
		"is_dir":   info.IsDir(),
		"mode":     info.Mode().String(),
		"mod_time": info.ModTime().UTC().Format(time.RFC3339),
	}
}

func handleSystemInfo(params map[string]interface{}) map[string]interface{} {
	hostname, _ := os.Hostname()

	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)

	// Get disk usage for root
	var diskTotal, diskFree uint64
	if stat, err := os.Stat("/"); err == nil {
		if statfs, ok := stat.Sys().(*syscall.Statfs_t); ok {
			diskTotal = statfs.Blocks * uint64(statfs.Bsize)
			diskFree = statfs.Bfree * uint64(statfs.Bsize)
		}
	}

	return map[string]interface{}{
		"success":      true,
		"hostname":     hostname,
		"os":           runtime.GOOS,
		"arch":         runtime.GOARCH,
		"num_cpu":      runtime.NumCPU(),
		"go_version":   runtime.Version(),
		"memory_alloc": memStats.Alloc,
		"memory_sys":   memStats.Sys,
		"disk_total":   diskTotal,
		"disk_free":    diskFree,
	}
}

func handleListProcesses(params map[string]interface{}) map[string]interface{} {
	// Use ps command for simplicity
	cmd := exec.Command("ps", "aux")
	output, err := cmd.CombinedOutput()

	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success": true,
		"output":  string(output),
	}
}

func handleKillProcess(params map[string]interface{}) map[string]interface{} {
	pid, _ := params["pid"].(float64)
	signal, _ := params["signal"].(float64)

	if pid == 0 {
		return map[string]interface{}{
			"success": false,
			"error":   "no pid provided",
		}
	}

	if signal == 0 {
		signal = 15 // SIGTERM
	}

	process, err := os.FindProcess(int(pid))
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	err = process.Signal(syscall.Signal(int(signal)))
	if err != nil {
		return map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		}
	}

	return map[string]interface{}{
		"success": true,
		"pid":     int(pid),
		"signal":  int(signal),
	}
}

func handleDocker(params map[string]interface{}) map[string]interface{} {
	args, _ := params["args"].([]interface{})

	cmdArgs := []string{}
	for _, arg := range args {
		if s, ok := arg.(string); ok {
			cmdArgs = append(cmdArgs, s)
		}
	}

	cmd := exec.Command("docker", cmdArgs...)
	output, err := cmd.CombinedOutput()

	result := map[string]interface{}{
		"success": err == nil,
		"output":  string(output),
	}

	if err != nil {
		result["error"] = err.Error()
	}

	return result
}

func handleGit(params map[string]interface{}) map[string]interface{} {
	args, _ := params["args"].([]interface{})
	workDir, _ := params["working_directory"].(string)

	cmdArgs := []string{}
	for _, arg := range args {
		if s, ok := arg.(string); ok {
			cmdArgs = append(cmdArgs, s)
		}
	}

	cmd := exec.Command("git", cmdArgs...)
	if workDir != "" {
		cmd.Dir = workDir
	}

	output, err := cmd.CombinedOutput()

	result := map[string]interface{}{
		"success": err == nil,
		"output":  string(output),
	}

	if err != nil {
		result["error"] = err.Error()
	}

	return result
}

func handleManageService(params map[string]interface{}) map[string]interface{} {
	action, _ := params["action"].(string)
	serviceName, _ := params["service_name"].(string)

	if serviceName == "" {
		return map[string]interface{}{
			"success": false,
			"error":   "no service_name provided",
		}
	}

	if action == "" {
		action = "status"
	}

	// Try systemctl first, fall back to service
	var cmd *exec.Cmd
	if _, err := exec.LookPath("systemctl"); err == nil {
		cmd = exec.Command("sudo", "systemctl", action, serviceName)
	} else {
		cmd = exec.Command("sudo", "service", serviceName, action)
	}

	output, err := cmd.CombinedOutput()

	result := map[string]interface{}{
		"success": err == nil,
		"output":  string(output),
		"service": serviceName,
		"action":  action,
	}

	if err != nil {
		result["error"] = err.Error()
	}

	return result
}
