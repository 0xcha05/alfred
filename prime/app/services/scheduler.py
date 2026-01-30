"""Scheduler service - triggers events on a schedule.

This enables Alfred to be proactive:
- "Remind me in 1 hour"
- "Check server health every 5 minutes"
- "Send me news at 9am daily"
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
import uuid

logger = logging.getLogger(__name__)

# Storage location
TASKS_FILE = Path("/home/ec2-user/alfred/data/scheduled_tasks.json")


@dataclass
class ScheduledTask:
    """A task that runs on a schedule."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""  # What the user asked for
    
    # When to run
    interval_minutes: Optional[int] = None  # Every N minutes
    cron: Optional[str] = None  # Cron expression (future)
    next_run: Optional[str] = None  # ISO timestamp
    
    # What to do
    action: str = ""  # Natural language instruction for the brain
    
    # Where to respond
    context: Dict[str, Any] = field(default_factory=dict)  # chat_id, etc.
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_run: Optional[str] = None
    run_count: int = 0
    enabled: bool = True
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "ScheduledTask":
        return cls(**data)


class Scheduler:
    """Manages scheduled tasks and triggers events when they're due."""
    
    def __init__(self):
        self.tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._check_interval = 30  # Check every 30 seconds
    
    async def start(self):
        """Start the scheduler."""
        # Ensure data directory exists
        TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing tasks
        self._load_tasks()
        
        # Start the scheduler loop
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info(f"Scheduler started with {len(self.tasks)} tasks")
    
    async def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._save_tasks()
        logger.info("Scheduler stopped")
    
    def _load_tasks(self):
        """Load tasks from disk."""
        if not TASKS_FILE.exists():
            return
        
        try:
            with open(TASKS_FILE, "r") as f:
                data = json.load(f)
                for task_data in data.get("tasks", []):
                    task = ScheduledTask.from_dict(task_data)
                    self.tasks[task.id] = task
            logger.info(f"Loaded {len(self.tasks)} scheduled tasks")
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")
    
    def _save_tasks(self):
        """Save tasks to disk."""
        try:
            with open(TASKS_FILE, "w") as f:
                json.dump({
                    "tasks": [t.to_dict() for t in self.tasks.values()],
                    "updated_at": datetime.utcnow().isoformat(),
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save tasks: {e}")
    
    async def add_task(
        self,
        name: str,
        description: str,
        interval_minutes: Optional[int] = None,
        cron: Optional[str] = None,
        action: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a new scheduled task."""
        
        task = ScheduledTask(
            name=name,
            description=description,
            interval_minutes=interval_minutes,
            cron=cron,
            action=action,
            context=context or {},
        )
        
        # Calculate next run time
        if interval_minutes:
            next_run = datetime.utcnow() + timedelta(minutes=interval_minutes)
            task.next_run = next_run.isoformat()
        
        self.tasks[task.id] = task
        self._save_tasks()
        
        logger.info(f"Added scheduled task: {task.id} - {name}")
        return task.id
    
    async def remove_task(self, task_id: str) -> bool:
        """Remove a scheduled task."""
        if task_id in self.tasks:
            del self.tasks[task_id]
            self._save_tasks()
            logger.info(f"Removed scheduled task: {task_id}")
            return True
        return False
    
    async def list_tasks(self) -> List[ScheduledTask]:
        """List all scheduled tasks."""
        return list(self.tasks.values())
    
    async def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Get a specific task."""
        return self.tasks.get(task_id)
    
    async def _scheduler_loop(self):
        """Main scheduler loop - checks for due tasks."""
        while self._running:
            try:
                await self._check_due_tasks()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)
                await asyncio.sleep(self._check_interval)
    
    async def _check_due_tasks(self):
        """Check for and execute due tasks."""
        now = datetime.utcnow()
        
        for task in list(self.tasks.values()):
            if not task.enabled or not task.next_run:
                continue
            
            next_run = datetime.fromisoformat(task.next_run)
            
            if now >= next_run:
                # Task is due!
                await self._execute_task(task)
                
                # Schedule next run
                if task.interval_minutes:
                    task.next_run = (now + timedelta(minutes=task.interval_minutes)).isoformat()
                else:
                    # One-time task, disable it
                    task.enabled = False
                
                task.last_run = now.isoformat()
                task.run_count += 1
                self._save_tasks()
    
    async def _execute_task(self, task: ScheduledTask):
        """Execute a scheduled task by creating an event."""
        from app.core.events import Event, event_bus
        
        logger.info(f"Executing scheduled task: {task.id} - {task.name}")
        
        # Create a schedule event (using strings, not enums)
        event = Event(
            source="schedule",
            type="tick",
            payload={
                "task_id": task.id,
                "task_name": task.name,
                "action": task.action,
                "description": task.description,
            },
            context=task.context,
        )
        
        # Publish to event bus
        await event_bus.publish(event)


# Global instance
scheduler = Scheduler()
