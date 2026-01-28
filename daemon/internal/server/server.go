// Package server is DEPRECATED.
//
// The daemon no longer runs a gRPC server. Instead, it connects TO Prime
// using a bidirectional TCP connection (see primeclient package).
//
// This file is kept for reference only.
package server

import (
	"github.com/alfred/daemon/internal/config"
	"github.com/alfred/daemon/internal/executor"
)

// Server is DEPRECATED - daemons now connect TO Prime instead of hosting a server.
type Server struct {
	config   *config.Config
	executor *executor.Executor
}

// New is DEPRECATED.
func New(cfg *config.Config, exec *executor.Executor) *Server {
	return &Server{
		config:   cfg,
		executor: exec,
	}
}
