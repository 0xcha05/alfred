// Package handlers - built-in command handlers.
// These are the default handlers that ship with the daemon.
// You can add more by calling handlers.Register().
package handlers

import (
	"context"
	"io/ioutil"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"

	"github.com/ultron/daemon/internal/browser"
	"github.com/ultron/daemon/internal/computer"
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

	// Computer use (Anthropic Computer Use API)
	Register("computer", handleComputer)

	// Browser automation
	Register("browser_launch", handleBrowserLaunch)
	Register("browser_goto", handleBrowserGoto)
	Register("browser_click", handleBrowserClick)
	Register("browser_type", handleBrowserType)
	Register("browser_get_text", handleBrowserGetText)
	Register("browser_get_content", handleBrowserGetContent)
	Register("browser_screenshot", handleBrowserScreenshot)
	Register("browser_evaluate", handleBrowserEvaluate)
	Register("browser_wait", handleBrowserWait)
	Register("browser_scroll", handleBrowserScroll)
	Register("browser_get_elements", handleBrowserGetElements)
	Register("browser_close", handleBrowserClose)
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

// Computer use handler (Anthropic Computer Use API)

func handleComputer(params map[string]interface{}) map[string]interface{} {
	result, err := computer.DefaultManager.ExecuteRaw(params)
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}

	// Pass through ALL fields from the Python result
	resp := map[string]interface{}{
		"success": result.Success,
	}
	if result.Error != "" {
		resp["error"] = result.Error
	}
	if result.Base64Image != "" {
		resp["base64_image"] = result.Base64Image
	}
	if result.DisplayWidth > 0 {
		resp["display_width"] = result.DisplayWidth
	}
	if result.DisplayHeight > 0 {
		resp["display_height"] = result.DisplayHeight
	}
	if result.ScreenWidth > 0 {
		resp["screen_width"] = result.ScreenWidth
	}
	if result.ScreenHeight > 0 {
		resp["screen_height"] = result.ScreenHeight
	}
	return resp
}

// Browser automation handlers

func handleBrowserLaunch(params map[string]interface{}) map[string]interface{} {
	headless, _ := params["headless"].(bool)
	useRealChrome := true // Default to real Chrome
	if val, ok := params["use_real_chrome"].(bool); ok {
		useRealChrome = val
	}

	result, err := browser.DefaultManager.Execute(browser.Command{
		Action:   "launch",
		Headless: headless,
		UseRealChrome: useRealChrome,
	})
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	resp := map[string]interface{}{
		"success": result.Success,
		"message": result.Message,
		"error":   result.Error,
	}
	if result.Error != "" && !result.Success {
		// Include instructions if connection failed
		resp["instructions"] = "Run: ./daemon/scripts/start_chrome.sh to start Chrome with debugging enabled"
	}
	return resp
}

func handleBrowserGoto(params map[string]interface{}) map[string]interface{} {
	url, _ := params["url"].(string)
	if url == "" {
		return map[string]interface{}{"success": false, "error": "url required"}
	}

	result, err := browser.DefaultManager.Goto(url)
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	return map[string]interface{}{
		"success": result.Success,
		"url":     result.URL,
		"title":   result.Title,
		"error":   result.Error,
	}
}

func handleBrowserClick(params map[string]interface{}) map[string]interface{} {
	selector, _ := params["selector"].(string)
	if selector == "" {
		return map[string]interface{}{"success": false, "error": "selector required"}
	}

	result, err := browser.DefaultManager.Click(selector)
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	return map[string]interface{}{
		"success": result.Success,
		"error":   result.Error,
	}
}

func handleBrowserType(params map[string]interface{}) map[string]interface{} {
	selector, _ := params["selector"].(string)
	text, _ := params["text"].(string)
	if selector == "" {
		return map[string]interface{}{"success": false, "error": "selector required"}
	}

	result, err := browser.DefaultManager.Type(selector, text)
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	return map[string]interface{}{
		"success": result.Success,
		"error":   result.Error,
	}
}

func handleBrowserGetText(params map[string]interface{}) map[string]interface{} {
	selector, _ := params["selector"].(string)
	if selector == "" {
		return map[string]interface{}{"success": false, "error": "selector required"}
	}

	result, err := browser.DefaultManager.GetText(selector)
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	return map[string]interface{}{
		"success": result.Success,
		"text":    result.Text,
		"error":   result.Error,
	}
}

func handleBrowserGetContent(params map[string]interface{}) map[string]interface{} {
	result, err := browser.DefaultManager.GetContent()
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	return map[string]interface{}{
		"success": result.Success,
		"content": result.Content,
		"url":     result.URL,
		"title":   result.Title,
		"error":   result.Error,
	}
}

func handleBrowserScreenshot(params map[string]interface{}) map[string]interface{} {
	path, _ := params["path"].(string)
	fullPage, _ := params["full_page"].(bool)
	if path == "" {
		path = "/tmp/screenshot.png"
	}

	result, err := browser.DefaultManager.Screenshot(path, fullPage)
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	return map[string]interface{}{
		"success": result.Success,
		"path":    result.Path,
		"error":   result.Error,
	}
}

func handleBrowserEvaluate(params map[string]interface{}) map[string]interface{} {
	script, _ := params["script"].(string)
	if script == "" {
		return map[string]interface{}{"success": false, "error": "script required"}
	}

	result, err := browser.DefaultManager.Evaluate(script)
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	return map[string]interface{}{
		"success": result.Success,
		"result":  result.Result,
		"error":   result.Error,
	}
}

func handleBrowserWait(params map[string]interface{}) map[string]interface{} {
	selector, _ := params["selector"].(string)
	timeout, _ := params["timeout"].(float64)
	if selector == "" {
		return map[string]interface{}{"success": false, "error": "selector required"}
	}
	if timeout == 0 {
		timeout = 10000
	}

	result, err := browser.DefaultManager.Wait(selector, int(timeout))
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	return map[string]interface{}{
		"success": result.Success,
		"error":   result.Error,
	}
}

func handleBrowserScroll(params map[string]interface{}) map[string]interface{} {
	direction, _ := params["direction"].(string)
	amount, _ := params["amount"].(float64)
	if direction == "" {
		direction = "down"
	}
	if amount == 0 {
		amount = 500
	}

	result, err := browser.DefaultManager.Execute(browser.Command{
		Action:    "scroll",
		Direction: direction,
		Amount:    int(amount),
	})
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	return map[string]interface{}{
		"success": result.Success,
		"error":   result.Error,
	}
}

func handleBrowserGetElements(params map[string]interface{}) map[string]interface{} {
	selector, _ := params["selector"].(string)
	if selector == "" {
		return map[string]interface{}{"success": false, "error": "selector required"}
	}

	result, err := browser.DefaultManager.Execute(browser.Command{
		Action:   "get_elements",
		Selector: selector,
	})
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	return map[string]interface{}{
		"success":  result.Success,
		"elements": result.Elements,
		"count":    result.Count,
		"error":    result.Error,
	}
}

func handleBrowserClose(params map[string]interface{}) map[string]interface{} {
	result, err := browser.DefaultManager.Close()
	if err != nil {
		return map[string]interface{}{"success": false, "error": err.Error()}
	}
	return map[string]interface{}{
		"success": result.Success,
		"message": result.Message,
		"error":   result.Error,
	}
}
