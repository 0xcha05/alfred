package server

import (
	"context"
	"log"
	"time"

	"github.com/alfred/daemon/internal/config"
	"github.com/alfred/daemon/internal/executor"
	"github.com/alfred/daemon/internal/session"
	pb "github.com/alfred/daemon/pkg/proto"
	"google.golang.org/grpc"
)

// Server implements the DaemonService gRPC interface
type Server struct {
	pb.UnimplementedDaemonServiceServer
	config         *config.Config
	executor       *executor.Executor
	sessionManager *session.Manager
}

// New creates a new daemon server
func New(cfg *config.Config, exec *executor.Executor) *Server {
	return &Server{
		config:         cfg,
		executor:       exec,
		sessionManager: session.NewManager(),
	}
}

// Register registers the daemon service with a gRPC server
func (s *Server) Register(grpcServer *grpc.Server) {
	pb.RegisterDaemonServiceServer(grpcServer, s)
}

// Heartbeat handles heartbeat requests
func (s *Server) Heartbeat(ctx context.Context, req *pb.HeartbeatRequest) (*pb.HeartbeatResponse, error) {
	return &pb.HeartbeatResponse{
		Ok:           true,
		PendingTasks: nil,
	}, nil
}

// ExecuteShell executes a shell command and streams output
func (s *Server) ExecuteShell(req *pb.ShellRequest, stream pb.DaemonService_ExecuteShellServer) error {
	ctx := stream.Context()

	// Set timeout
	timeout := time.Duration(req.TimeoutSeconds) * time.Second
	if timeout == 0 {
		timeout = 5 * time.Minute // Default 5 minute timeout
	}

	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	// Create output channel
	outputChan := make(chan string, 100)
	done := make(chan struct{})

	// Stream output as it comes
	go func() {
		defer close(done)
		for line := range outputChan {
			if err := stream.Send(&pb.ShellResponse{
				Output:     &pb.ShellResponse_Stdout{Stdout: line + "\n"},
				IsComplete: false,
			}); err != nil {
				log.Printf("Failed to send output: %v", err)
				return
			}
		}
	}()

	// Execute command
	result, err := s.executor.ExecuteShell(ctx, req.Command, req.WorkingDirectory, req.Environment, outputChan)
	close(outputChan)

	// Wait for streaming to complete
	<-done

	// Send final response
	if err != nil {
		return stream.Send(&pb.ShellResponse{
			IsComplete: true,
			ExitCode:   -1,
			Error:      err.Error(),
		})
	}

	return stream.Send(&pb.ShellResponse{
		IsComplete: true,
		ExitCode:   int32(result.ExitCode),
	})
}

// ReadFile reads a file and returns its contents
func (s *Server) ReadFile(ctx context.Context, req *pb.ReadFileRequest) (*pb.ReadFileResponse, error) {
	content, size, err := s.executor.ReadFile(req.Path, req.Offset, req.Limit)
	if err != nil {
		return &pb.ReadFileResponse{
			Error: err.Error(),
		}, nil
	}

	return &pb.ReadFileResponse{
		Content:  content,
		Size:     size,
		IsBinary: isBinary(content),
	}, nil
}

// WriteFile writes content to a file
func (s *Server) WriteFile(ctx context.Context, req *pb.WriteFileRequest) (*pb.WriteFileResponse, error) {
	err := s.executor.WriteFile(req.Path, req.Content, req.CreateDirs, 0644)
	if err != nil {
		return &pb.WriteFileResponse{
			Success: false,
			Error:   err.Error(),
		}, nil
	}

	return &pb.WriteFileResponse{
		Success: true,
	}, nil
}

// ListFiles lists files in a directory
func (s *Server) ListFiles(ctx context.Context, req *pb.ListFilesRequest) (*pb.ListFilesResponse, error) {
	files, err := s.executor.ListFiles(req.Path, req.Recursive, req.Pattern)
	if err != nil {
		return &pb.ListFilesResponse{
			Error: err.Error(),
		}, nil
	}

	pbFiles := make([]*pb.FileInfo, len(files))
	for i, f := range files {
		pbFiles[i] = &pb.FileInfo{
			Name:        f.Name,
			Path:        f.Path,
			Size:        f.Size,
			IsDirectory: f.IsDirectory,
			ModifiedAt:  f.ModifiedAt.Unix(),
			Mode:        int32(f.Mode),
		}
	}

	return &pb.ListFilesResponse{
		Files: pbFiles,
	}, nil
}

// CreateSession creates a new tmux session
func (s *Server) CreateSession(ctx context.Context, req *pb.CreateSessionRequest) (*pb.CreateSessionResponse, error) {
	sess, err := s.sessionManager.Create(req.Name, req.Command, req.WorkingDirectory)
	if err != nil {
		return &pb.CreateSessionResponse{
			Success: false,
			Error:   err.Error(),
		}, nil
	}

	log.Printf("Created session: %s", sess.ID)
	return &pb.CreateSessionResponse{
		SessionId: sess.ID,
		Success:   true,
	}, nil
}

// AttachSession attaches to a tmux session and streams output
func (s *Server) AttachSession(req *pb.AttachSessionRequest, stream pb.DaemonService_AttachSessionServer) error {
	outputChan, err := s.sessionManager.GetOutput(req.SessionId, req.Follow)
	if err != nil {
		return stream.Send(&pb.SessionOutput{
			Content:    err.Error(),
			IsComplete: true,
		})
	}

	for line := range outputChan {
		if err := stream.Send(&pb.SessionOutput{
			Content:    line + "\n",
			IsComplete: false,
		}); err != nil {
			return err
		}
	}

	return stream.Send(&pb.SessionOutput{
		IsComplete: true,
	})
}

// ListSessions lists all tmux sessions
func (s *Server) ListSessions(ctx context.Context, req *pb.ListSessionsRequest) (*pb.ListSessionsResponse, error) {
	sessions := s.sessionManager.List()
	pbSessions := make([]*pb.SessionInfo, len(sessions))

	for i, sess := range sessions {
		pbSessions[i] = &pb.SessionInfo{
			Id:        sess.ID,
			Name:      sess.Name,
			Command:   sess.Command,
			CreatedAt: sess.CreatedAt.Unix(),
			IsRunning: sess.IsRunning,
		}
	}

	return &pb.ListSessionsResponse{
		Sessions: pbSessions,
	}, nil
}

// KillSession kills a tmux session
func (s *Server) KillSession(ctx context.Context, req *pb.KillSessionRequest) (*pb.KillSessionResponse, error) {
	err := s.sessionManager.Kill(req.SessionId)
	if err != nil {
		return &pb.KillSessionResponse{
			Success: false,
			Error:   err.Error(),
		}, nil
	}

	log.Printf("Killed session: %s", req.SessionId)
	return &pb.KillSessionResponse{
		Success: true,
	}, nil
}

// isBinary checks if content appears to be binary
func isBinary(content []byte) bool {
	for _, b := range content {
		if b == 0 {
			return true
		}
	}
	return false
}
