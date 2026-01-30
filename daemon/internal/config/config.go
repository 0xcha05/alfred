package config

import (
	"bufio"
	"os"
	"strconv"
	"strings"
)

// loadEnvFile loads environment variables from a .env file
func loadEnvFile(path string) {
	file, err := os.Open(path)
	if err != nil {
		return // File doesn't exist, that's fine
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		// Skip empty lines and comments
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		// Parse KEY=value
		parts := strings.SplitN(line, "=", 2)
		if len(parts) == 2 {
			key := strings.TrimSpace(parts[0])
			value := strings.TrimSpace(parts[1])
			// Only set if not already set (env vars take precedence)
			if os.Getenv(key) == "" {
				os.Setenv(key, value)
			}
		}
	}
}

// Config holds daemon configuration
type Config struct {
	// Identity
	Name         string
	Hostname     string
	Capabilities []string

	// Networking
	PrimeAddress string // TCP address to connect to Prime (e.g., "prime.example.com:50051")
	PrimeURL     string // HTTP URL for Prime (legacy, for health checks)

	// Security
	RegistrationKey string
	TLSCertPath     string
	TLSKeyPath      string

	// Soul Daemon (daemon on Prime's server for self-modification)
	IsSoulDaemon bool   // True if this daemon runs on Prime's server
	AlfredRoot   string // Root directory of Alfred installation

	// Runtime
	DaemonID string // Assigned by Prime after registration
}

// Load loads configuration from environment variables or config file
func Load(configPath string) (*Config, error) {
	// Try to load .env file from current directory
	loadEnvFile(".env")
	// Also try from daemon directory if run from elsewhere
	loadEnvFile("daemon/.env")
	
	hostname, _ := os.Hostname()

	// Default capabilities - full control
	defaultCaps := []string{
		"shell", "files", "docker", "services", "git", "network",
		"process", "package", "cron", "session",
	}

	cfg := &Config{
		Name:            getEnv("DAEMON_NAME", hostname),
		Hostname:        hostname,
		Capabilities:    getEnvSlice("DAEMON_CAPABILITIES", defaultCaps),
		PrimeAddress:    getEnv("PRIME_ADDRESS", "localhost:50051"),
		PrimeURL:        getEnv("PRIME_URL", "http://localhost:8000"),
		RegistrationKey: getEnv("DAEMON_REGISTRATION_KEY", ""),
		TLSCertPath:     getEnv("DAEMON_TLS_CERT", ""),
		TLSKeyPath:      getEnv("DAEMON_TLS_KEY", ""),
		IsSoulDaemon:    getEnvBool("DAEMON_IS_SOUL", false),
		AlfredRoot:      getEnv("ALFRED_ROOT", ""),
	}

	// Soul daemon gets additional capabilities
	if cfg.IsSoulDaemon {
		cfg.Capabilities = append(cfg.Capabilities, "soul", "self-modify")
	}

	return cfg, nil
}

func getEnvBool(key string, defaultValue bool) bool {
	if value := os.Getenv(key); value != "" {
		lower := strings.ToLower(value)
		return lower == "true" || lower == "1" || lower == "yes"
	}
	return defaultValue
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvInt(key string, defaultValue int) int {
	if value := os.Getenv(key); value != "" {
		if i, err := strconv.Atoi(value); err == nil {
			return i
		}
	}
	return defaultValue
}

func getEnvSlice(key string, defaultValue []string) []string {
	if value := os.Getenv(key); value != "" {
		return strings.Split(value, ",")
	}
	return defaultValue
}
