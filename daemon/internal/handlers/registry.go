// Package handlers provides a flexible command handler registry.
// Commands are registered by type string, not hardcoded in a switch statement.
package handlers

import (
	"fmt"
	"sync"
)

// Handler is a function that handles a command and returns a result.
type Handler func(params map[string]interface{}) map[string]interface{}

// Registry manages command handlers.
type Registry struct {
	handlers map[string]Handler
	mu       sync.RWMutex
}

// NewRegistry creates a new handler registry.
func NewRegistry() *Registry {
	return &Registry{
		handlers: make(map[string]Handler),
	}
}

// Register adds a handler for a command type.
// This is how you extend the daemon's capabilities without changing core code.
func (r *Registry) Register(cmdType string, handler Handler) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.handlers[cmdType] = handler
}

// Handle executes the handler for the given command type.
func (r *Registry) Handle(cmdType string, params map[string]interface{}) map[string]interface{} {
	r.mu.RLock()
	handler, exists := r.handlers[cmdType]
	r.mu.RUnlock()

	if !exists {
		return map[string]interface{}{
			"success": false,
			"error":   fmt.Sprintf("unknown command type: %s", cmdType),
		}
	}

	return handler(params)
}

// HasHandler checks if a handler exists for the command type.
func (r *Registry) HasHandler(cmdType string) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	_, exists := r.handlers[cmdType]
	return exists
}

// ListHandlers returns all registered command types.
func (r *Registry) ListHandlers() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	types := make([]string, 0, len(r.handlers))
	for t := range r.handlers {
		types = append(types, t)
	}
	return types
}

// Global registry instance
var DefaultRegistry = NewRegistry()

// Register is a convenience function to register with the default registry.
func Register(cmdType string, handler Handler) {
	DefaultRegistry.Register(cmdType, handler)
}

// Handle is a convenience function to handle with the default registry.
func Handle(cmdType string, params map[string]interface{}) map[string]interface{} {
	return DefaultRegistry.Handle(cmdType, params)
}
