// Package emitters provides event emission capabilities.
// Emitters watch for conditions and emit events to Prime.
package emitters

import (
	"context"
	"log"
	"sync"
	"time"
)

// Event represents something that happened on the daemon.
type Event struct {
	Source    string                 `json:"source"`     // e.g., "daemon:macbook"
	Type      string                 `json:"type"`       // e.g., "file_changed", "cpu_high"
	Payload   map[string]interface{} `json:"payload"`    // Event data
	Timestamp time.Time              `json:"timestamp"`
}

// EventCallback is called when an event is emitted.
type EventCallback func(event Event)

// Emitter is something that can emit events.
type Emitter interface {
	Start(ctx context.Context) error
	Stop() error
	Name() string
}

// Manager manages all emitters and routes events.
type Manager struct {
	emitters  []Emitter
	callbacks []EventCallback
	mu        sync.RWMutex
	ctx       context.Context
	cancel    context.CancelFunc
}

// NewManager creates a new emitter manager.
func NewManager() *Manager {
	return &Manager{
		emitters:  make([]Emitter, 0),
		callbacks: make([]EventCallback, 0),
	}
}

// AddEmitter adds an emitter to the manager.
func (m *Manager) AddEmitter(e Emitter) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.emitters = append(m.emitters, e)
}

// OnEvent registers a callback for events.
func (m *Manager) OnEvent(callback EventCallback) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.callbacks = append(m.callbacks, callback)
}

// Emit sends an event to all callbacks.
func (m *Manager) Emit(event Event) {
	m.mu.RLock()
	callbacks := m.callbacks
	m.mu.RUnlock()

	for _, cb := range callbacks {
		go cb(event)
	}
}

// Start starts all emitters.
func (m *Manager) Start() error {
	m.ctx, m.cancel = context.WithCancel(context.Background())

	m.mu.RLock()
	emitters := m.emitters
	m.mu.RUnlock()

	for _, e := range emitters {
		log.Printf("Starting emitter: %s", e.Name())
		go func(emitter Emitter) {
			if err := emitter.Start(m.ctx); err != nil {
				log.Printf("Emitter %s error: %v", emitter.Name(), err)
			}
		}(e)
	}

	return nil
}

// Stop stops all emitters.
func (m *Manager) Stop() error {
	if m.cancel != nil {
		m.cancel()
	}

	m.mu.RLock()
	emitters := m.emitters
	m.mu.RUnlock()

	for _, e := range emitters {
		e.Stop()
	}

	return nil
}

// Global manager instance
var DefaultManager = NewManager()
