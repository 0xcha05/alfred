package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/alfred/daemon/internal/config"
	"github.com/alfred/daemon/internal/emitters"
	"github.com/alfred/daemon/internal/handlers"
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

	// Register built-in command handlers
	handlers.RegisterBuiltins()
	log.Printf("   Registered handlers: %v", handlers.DefaultRegistry.ListHandlers())

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

	// Set up emitters for proactive events
	emitterManager := emitters.NewManager()

	// Add resource monitor
	resourceMonitor := emitters.NewResourceMonitor(emitterManager, cfg.Name)
	emitterManager.AddEmitter(resourceMonitor)

	// Route emitter events to Prime
	emitterManager.OnEvent(func(event emitters.Event) {
		log.Printf("Emitting event: %s/%s", event.Source, event.Type)
		if err := client.SendEvent(event.Source, event.Type, event.Payload); err != nil {
			log.Printf("Failed to send event: %v", err)
		}
	})

	// Context for lifecycle management
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle shutdown signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Start emitters
	if err := emitterManager.Start(); err != nil {
		log.Printf("Failed to start emitters: %v", err)
	}

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

	// Stop emitters
	emitterManager.Stop()

	// Close client
	if err := client.Close(); err != nil {
		log.Printf("Error closing client: %v", err)
	}

	log.Println("Goodbye!")
}
