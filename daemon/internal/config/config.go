package config

import (
	"os"
	"strconv"
	"strings"
)

// Config holds daemon configuration
type Config struct {
	// Identity
	Name         string
	Hostname     string
	Capabilities []string

	// Networking
	GRPCPort        int
	PrimeURL        string
	ExternalAddress string // Address Prime should use to connect back (if different from hostname:port)

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
		GRPCPort:        getEnvInt("DAEMON_GRPC_PORT", 50052),
		PrimeURL:        getEnv("PRIME_URL", "http://localhost:8000"),
		ExternalAddress: getEnv("DAEMON_EXTERNAL_ADDRESS", ""),
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
