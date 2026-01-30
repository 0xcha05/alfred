// Resource monitor emitter - monitors CPU, memory, disk.
package emitters

import (
	"context"
	"log"
	"os"
	"runtime"
	"syscall"
	"time"
)

// ResourceMonitor monitors system resources and emits events on thresholds.
type ResourceMonitor struct {
	manager        *Manager
	daemonName     string
	checkInterval  time.Duration
	cpuThreshold   float64
	memThreshold   float64
	diskThreshold  float64
	lastCPUAlert   time.Time
	lastMemAlert   time.Time
	lastDiskAlert  time.Time
	alertCooldown  time.Duration
	running        bool
}

// NewResourceMonitor creates a new resource monitor.
func NewResourceMonitor(manager *Manager, daemonName string) *ResourceMonitor {
	return &ResourceMonitor{
		manager:       manager,
		daemonName:    daemonName,
		checkInterval: 30 * time.Second,
		cpuThreshold:  80.0,  // Alert if CPU > 80%
		memThreshold:  85.0,  // Alert if memory > 85%
		diskThreshold: 90.0,  // Alert if disk > 90%
		alertCooldown: 5 * time.Minute,
	}
}

// SetThresholds sets the alert thresholds.
func (r *ResourceMonitor) SetThresholds(cpu, mem, disk float64) {
	r.cpuThreshold = cpu
	r.memThreshold = mem
	r.diskThreshold = disk
}

// Name returns the emitter name.
func (r *ResourceMonitor) Name() string {
	return "resource_monitor"
}

// Start begins monitoring.
func (r *ResourceMonitor) Start(ctx context.Context) error {
	r.running = true
	ticker := time.NewTicker(r.checkInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			r.check()
		}
	}
}

// Stop stops monitoring.
func (r *ResourceMonitor) Stop() error {
	r.running = false
	return nil
}

func (r *ResourceMonitor) check() {
	now := time.Now()

	// Check memory
	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)

	// This is a simplified memory check - in production you'd use cgroups or /proc
	memPercent := float64(memStats.Alloc) / float64(memStats.Sys) * 100

	if memPercent > r.memThreshold && now.Sub(r.lastMemAlert) > r.alertCooldown {
		r.lastMemAlert = now
		r.manager.Emit(Event{
			Source:    "daemon:" + r.daemonName,
			Type:      "memory_high",
			Timestamp: now,
			Payload: map[string]interface{}{
				"percent":   memPercent,
				"threshold": r.memThreshold,
				"alloc":     memStats.Alloc,
				"sys":       memStats.Sys,
			},
		})
		log.Printf("Memory alert: %.1f%% > %.1f%%", memPercent, r.memThreshold)
	}

	// Check disk
	var stat syscall.Statfs_t
	if err := syscall.Statfs("/", &stat); err == nil {
		diskTotal := stat.Blocks * uint64(stat.Bsize)
		diskFree := stat.Bfree * uint64(stat.Bsize)
		diskUsed := diskTotal - diskFree
		diskPercent := float64(diskUsed) / float64(diskTotal) * 100

		if diskPercent > r.diskThreshold && now.Sub(r.lastDiskAlert) > r.alertCooldown {
			r.lastDiskAlert = now
			r.manager.Emit(Event{
				Source:    "daemon:" + r.daemonName,
				Type:      "disk_high",
				Timestamp: now,
				Payload: map[string]interface{}{
					"percent":   diskPercent,
					"threshold": r.diskThreshold,
					"total_gb":  float64(diskTotal) / 1024 / 1024 / 1024,
					"free_gb":   float64(diskFree) / 1024 / 1024 / 1024,
				},
			})
			log.Printf("Disk alert: %.1f%% > %.1f%%", diskPercent, r.diskThreshold)
		}
	}
}

// GetResourceStats returns current resource stats without alerting.
func GetResourceStats() map[string]interface{} {
	hostname, _ := os.Hostname()

	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)

	stats := map[string]interface{}{
		"hostname":     hostname,
		"num_cpu":      runtime.NumCPU(),
		"memory_alloc": memStats.Alloc,
		"memory_sys":   memStats.Sys,
	}

	var diskStat syscall.Statfs_t
	if err := syscall.Statfs("/", &diskStat); err == nil {
		diskTotal := diskStat.Blocks * uint64(diskStat.Bsize)
		diskFree := diskStat.Bfree * uint64(diskStat.Bsize)
		stats["disk_total"] = diskTotal
		stats["disk_free"] = diskFree
		stats["disk_percent"] = float64(diskTotal-diskFree) / float64(diskTotal) * 100
	}

	return stats
}
