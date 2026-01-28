package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/alfred/daemon/internal/config"
	"github.com/alfred/daemon/internal/primeclient"
)

func main() {
	// Parse flags
	configPath := flag.String("config", "", "Path to config file")
	flag.Parse()

	// Load configuration
	cfg, err := config.Load(*configPath)
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}

	log.Printf("🤖 Alfred Daemon starting...")
	log.Printf("   Name: %s", cfg.Name)
	log.Printf("   Hostname: %s", cfg.Hostname)
	log.Printf("   Capabilities: %v", cfg.Capabilities)
	log.Printf("   Prime address: %s", cfg.PrimeAddress)
	if cfg.IsSoulDaemon {
		log.Printf("   Mode: SOUL DAEMON (can modify Alfred)")
		log.Printf("   Alfred root: %s", cfg.AlfredRoot)
	}

	// Create Prime client
	client := primeclient.NewClient(primeclient.Config{
		PrimeAddress:    cfg.PrimeAddress,
		RegistrationKey: cfg.RegistrationKey,
		Name:            cfg.Name,
		Hostname:        cfg.Hostname,
		Capabilities:    cfg.Capabilities,
		IsSoulDaemon:    cfg.IsSoulDaemon,
		AlfredRoot:      cfg.AlfredRoot,
	})

	// Context for lifecycle management
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle shutdown signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Connect to Prime in background
	go func() {
		log.Printf("Connecting to Prime at %s...", cfg.PrimeAddress)
		if err := client.Connect(ctx); err != nil {
			if err != context.Canceled {
				log.Printf("Connection error: %v", err)
			}
		}
	}()

	// Wait for shutdown signal
	sig := <-sigChan
	log.Printf("Received signal %v, shutting down...", sig)
	cancel()

	// Close client
	if err := client.Close(); err != nil {
		log.Printf("Error closing client: %v", err)
	}

	log.Println("Goodbye!")
}
