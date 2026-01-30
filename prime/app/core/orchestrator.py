"""Task orchestration and parallel execution."""

import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """Represents a task to be executed."""
    id: str
    daemon_id: str
    action: str
    parameters: dict
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Orchestrator:
    """Manages parallel task execution across daemons."""
    
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
    
    def create_task(self, daemon_id: str, action: str, parameters: dict) -> Task:
        """Create a new task."""
        task = Task(
            id=str(uuid.uuid4())[:8],
            daemon_id=daemon_id,
            action=action,
            parameters=parameters,
        )
        self.tasks[task.id] = task
        return task
    
    async def execute_task(self, task: Task) -> Task:
        """Execute a single task on its assigned daemon."""
        from app.grpc_server import daemon_registry, execute_shell, read_file, write_file, list_files
        
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        
        try:
            # Check if connected to daemon
            if not daemon_registry.is_connected(task.daemon_id):
                raise Exception(f"Daemon {task.daemon_id} not connected")
            
            # Execute based on action type
            if task.action == "shell":
                result = await self._execute_shell(task.daemon_id, task.parameters)
            elif task.action == "read_file":
                result = await self._execute_read_file(task.daemon_id, task.parameters)
            elif task.action == "write_file":
                result = await self._execute_write_file(task.daemon_id, task.parameters)
            elif task.action == "list_files":
                result = await self._execute_list_files(task.daemon_id, task.parameters)
            else:
                raise Exception(f"Unknown action: {task.action}")
            
            task.result = result
            task.status = TaskStatus.COMPLETED
            
        except Exception as e:
            task.error = str(e)
            task.status = TaskStatus.FAILED
        
        task.completed_at = datetime.utcnow()
        return task
    
    async def execute_parallel(self, tasks: List[Task]) -> List[Task]:
        """Execute multiple tasks in parallel."""
        if not tasks:
            return []
        
        # Run all tasks concurrently
        results = await asyncio.gather(
            *[self.execute_task(task) for task in tasks],
            return_exceptions=True,
        )
        
        # Handle any exceptions
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                tasks[i].status = TaskStatus.FAILED
                tasks[i].error = str(result)
        
        return tasks
    
    async def _execute_shell(self, daemon_id: str, params: dict) -> dict:
        """Execute shell command via daemon registry."""
        from app.grpc_server import execute_shell
        
        command = params.get("command", "")
        working_dir = params.get("working_directory", "")
        timeout = params.get("timeout_seconds", 300)
        use_sudo = params.get("use_sudo", False)
        
        try:
            result = await execute_shell(
                daemon_id=daemon_id,
                command=command,
                working_directory=working_dir,
                timeout=float(timeout),
                use_sudo=use_sudo,
            )
            return result
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    async def _execute_read_file(self, daemon_id: str, params: dict) -> dict:
        """Read file via daemon registry."""
        from app.grpc_server import read_file
        
        path = params.get("path", "")
        
        try:
            result = await read_file(daemon_id, path)
            return result
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    async def _execute_write_file(self, daemon_id: str, params: dict) -> dict:
        """Write file via daemon registry."""
        from app.grpc_server import write_file
        
        path = params.get("path", "")
        content = params.get("content", "")
        
        try:
            content_bytes = content.encode('utf-8') if isinstance(content, str) else content
            result = await write_file(daemon_id, path, content_bytes)
            return result
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    async def _execute_list_files(self, daemon_id: str, params: dict) -> dict:
        """List files via daemon registry."""
        from app.grpc_server import list_files
        
        path = params.get("path", ".")
        recursive = params.get("recursive", False)
        
        try:
            result = await list_files(daemon_id, path, recursive)
            return result
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def get_running_tasks(self) -> List[Task]:
        """Get all currently running tasks."""
        return [t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]
    
    def get_task_summary(self) -> dict:
        """Get summary of all tasks."""
        running = [t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]
        
        summary = []
        for task in running:
            elapsed = (datetime.utcnow() - task.started_at).seconds if task.started_at else 0
            summary.append({
                "id": task.id,
                "action": task.action,
                "daemon": task.daemon_id,
                "running_for": f"{elapsed}s",
            })
        
        return {
            "running_count": len(running),
            "tasks": summary,
        }


# Global orchestrator instance
orchestrator = Orchestrator()
