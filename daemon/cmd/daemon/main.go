package main

import (
	"context"
	"crypto/tls"
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/alfred/daemon/internal/client"
	"github.com/alfred/daemon/internal/config"
	"github.com/alfred/daemon/internal/executor"
	"github.com/alfred/daemon/internal/server"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
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
	log.Printf("   gRPC port: %d", cfg.GRPCPort)
	log.Printf("   Prime URL: %s", cfg.PrimeURL)

	// Create executor
	exec := executor.New()

	// Create gRPC server with TLS
	var opts []grpc.ServerOption

	if cfg.TLSCertPath != "" && cfg.TLSKeyPath != "" {
		cert, err := tls.LoadX509KeyPair(cfg.TLSCertPath, cfg.TLSKeyPath)
		if err != nil {
			log.Fatalf("Failed to load TLS certificates: %v", err)
		}
		tlsConfig := &tls.Config{
			Certificates: []tls.Certificate{cert},
			MinVersion:   tls.VersionTLS12,
		}
		opts = append(opts, grpc.Creds(credentials.NewTLS(tlsConfig)))
		log.Printf("   TLS: enabled")
	} else {
		log.Printf("   TLS: disabled (development mode)")
	}

	grpcServer := grpc.NewServer(opts...)

	// Create and register daemon service
	daemonServer := server.New(cfg, exec)
	daemonServer.Register(grpcServer)

	// Start gRPC server
	lis, err := net.Listen("tcp", fmt.Sprintf(":%d", cfg.GRPCPort))
	if err != nil {
		log.Fatalf("Failed to listen: %v", err)
	}

	// Start gRPC server in background
	go func() {
		log.Printf("🤖 Alfred Daemon gRPC server ready on port %d", cfg.GRPCPort)
		if err := grpcServer.Serve(lis); err != nil {
			log.Fatalf("Failed to serve: %v", err)
		}
	}()

	// Create Prime client
	primeClient := client.NewPrimeClient(cfg.PrimeURL, cfg.RegistrationKey)

	// Context for lifecycle management
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Register with Prime
	go func() {
		// Wait a bit for gRPC server to be ready
		time.Sleep(1 * time.Second)

		// Determine our gRPC address for Prime to connect back
		grpcAddr := fmt.Sprintf("%s:%d", cfg.Hostname, cfg.GRPCPort)
		if cfg.ExternalAddress != "" {
			grpcAddr = cfg.ExternalAddress
		}

		log.Printf("Registering with Prime at %s...", cfg.PrimeURL)
		if cfg.IsSoulDaemon {
			log.Printf("Registering as SOUL DAEMON (can modify Alfred)")
		}
		resp, err := primeClient.Register(ctx, client.RegistrationRequest{
			Name:         cfg.Name,
			Hostname:     cfg.Hostname,
			Capabilities: cfg.Capabilities,
			GRPCAddress:  grpcAddr,
			IsSoulDaemon: cfg.IsSoulDaemon,
			AlfredRoot:   cfg.AlfredRoot,
		})
		if err != nil {
			log.Printf("Warning: Failed to register with Prime: %v", err)
			log.Printf("Daemon will continue running, retry registration manually")
			return
		}

		log.Printf("✓ Registered with Prime as %s", resp.DaemonID)
		cfg.DaemonID = resp.DaemonID

		// Start heartbeat loop
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()

		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if err := primeClient.Heartbeat(ctx); err != nil {
					log.Printf("Heartbeat failed: %v", err)
				} else {
					log.Printf("♥ Heartbeat sent")
				}
			}
		}
	}()

	// Handle shutdown signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	<-sigChan
	log.Println("Shutting down...")
	cancel()
	grpcServer.GracefulStop()
	log.Println("Goodbye!")
}
