// File watcher emitter - watches files/directories for changes.
package emitters

import (
	"context"
	"log"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// FileWatch represents a watched file or directory.
type FileWatch struct {
	Path      string
	Recursive bool
	Pattern   string // Optional glob pattern
	EventMask uint32 // What events to watch (create, modify, delete)
}

// Event masks
const (
	EventCreate = 1 << iota
	EventModify
	EventDelete
	EventAll = EventCreate | EventModify | EventDelete
)

// FileWatcher watches files and directories for changes.
type FileWatcher struct {
	manager    *Manager
	daemonName string
	watches    map[string]*FileWatch
	fileStates map[string]time.Time // Track mod times
	mu         sync.RWMutex
	interval   time.Duration
	running    bool
}

// NewFileWatcher creates a new file watcher.
func NewFileWatcher(manager *Manager, daemonName string) *FileWatcher {
	return &FileWatcher{
		manager:    manager,
		daemonName: daemonName,
		watches:    make(map[string]*FileWatch),
		fileStates: make(map[string]time.Time),
		interval:   5 * time.Second,
	}
}

// Name returns the emitter name.
func (f *FileWatcher) Name() string {
	return "file_watcher"
}

// Watch adds a path to watch.
func (f *FileWatcher) Watch(path string, recursive bool, pattern string) error {
	f.mu.Lock()
	defer f.mu.Unlock()

	absPath, err := filepath.Abs(path)
	if err != nil {
		return err
	}

	f.watches[absPath] = &FileWatch{
		Path:      absPath,
		Recursive: recursive,
		Pattern:   pattern,
		EventMask: EventAll,
	}

	log.Printf("Watching: %s (recursive=%v, pattern=%s)", absPath, recursive, pattern)
	return nil
}

// Unwatch removes a path from watching.
func (f *FileWatcher) Unwatch(path string) {
	f.mu.Lock()
	defer f.mu.Unlock()

	absPath, _ := filepath.Abs(path)
	delete(f.watches, absPath)
}

// Start begins watching.
func (f *FileWatcher) Start(ctx context.Context) error {
	f.running = true

	// Initial scan to get baseline
	f.scan()

	ticker := time.NewTicker(f.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			f.scan()
		}
	}
}

// Stop stops watching.
func (f *FileWatcher) Stop() error {
	f.running = false
	return nil
}

func (f *FileWatcher) scan() {
	f.mu.RLock()
	watches := make([]*FileWatch, 0, len(f.watches))
	for _, w := range f.watches {
		watches = append(watches, w)
	}
	f.mu.RUnlock()

	newStates := make(map[string]time.Time)

	for _, watch := range watches {
		f.scanPath(watch, newStates)
	}

	// Compare with old states
	f.mu.Lock()
	defer f.mu.Unlock()

	// Check for modifications and creations
	for path, modTime := range newStates {
		oldTime, exists := f.fileStates[path]
		if !exists {
			// New file
			f.emitEvent("file_created", path, nil)
		} else if modTime.After(oldTime) {
			// Modified
			f.emitEvent("file_modified", path, nil)
		}
	}

	// Check for deletions
	for path := range f.fileStates {
		if _, exists := newStates[path]; !exists {
			f.emitEvent("file_deleted", path, nil)
		}
	}

	f.fileStates = newStates
}

func (f *FileWatcher) scanPath(watch *FileWatch, states map[string]time.Time) {
	if watch.Recursive {
		filepath.Walk(watch.Path, func(path string, info os.FileInfo, err error) error {
			if err != nil {
				return nil
			}
			if watch.Pattern != "" {
				if matched, _ := filepath.Match(watch.Pattern, info.Name()); !matched {
					return nil
				}
			}
			states[path] = info.ModTime()
			return nil
		})
	} else {
		info, err := os.Stat(watch.Path)
		if err != nil {
			return
		}

		if info.IsDir() {
			entries, err := os.ReadDir(watch.Path)
			if err != nil {
				return
			}
			for _, entry := range entries {
				if watch.Pattern != "" {
					if matched, _ := filepath.Match(watch.Pattern, entry.Name()); !matched {
						continue
					}
				}
				entryInfo, err := entry.Info()
				if err != nil {
					continue
				}
				path := filepath.Join(watch.Path, entry.Name())
				states[path] = entryInfo.ModTime()
			}
		} else {
			if watch.Pattern != "" {
				if matched, _ := filepath.Match(watch.Pattern, info.Name()); !matched {
					return
				}
			}
			states[watch.Path] = info.ModTime()
		}
	}
}

func (f *FileWatcher) emitEvent(eventType, path string, info os.FileInfo) {
	payload := map[string]interface{}{
		"path": path,
	}

	if info != nil {
		payload["size"] = info.Size()
		payload["is_dir"] = info.IsDir()
		payload["mod_time"] = info.ModTime().UTC().Format(time.RFC3339)
	}

	f.manager.Emit(Event{
		Source:    "daemon:" + f.daemonName,
		Type:      eventType,
		Timestamp: time.Now(),
		Payload:   payload,
	})
}
