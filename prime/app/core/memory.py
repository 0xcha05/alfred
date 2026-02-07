"""Memory store interface for persistent context."""

from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel


class MachineInfo(BaseModel):
    """Machine/daemon information."""
    id: str
    name: str
    hostname: str
    capabilities: List[str]
    last_seen: datetime
    status: str


class ProjectInfo(BaseModel):
    """Project information."""
    name: str
    machine_id: str
    path: str
    run_command: Optional[str] = None
    test_command: Optional[str] = None
    deploy_command: Optional[str] = None


class Preference(BaseModel):
    """User preference."""
    key: str
    value: Any
    context: Optional[str] = None


class TaskHistory(BaseModel):
    """Historical task record."""
    id: str
    timestamp: datetime
    intent: str
    machine_id: str
    action: str
    parameters: dict
    result: Any
    success: bool
    duration_ms: int


class MemoryStore:
    """
    Memory store for Ultron's persistent context.
    
    Currently in-memory, will be backed by PostgreSQL.
    """
    
    def __init__(self):
        self.machines: dict[str, MachineInfo] = {}
        self.projects: dict[str, ProjectInfo] = {}
        self.preferences: dict[str, Preference] = {}
        self.history: list[TaskHistory] = []
    
    # Machine operations
    
    def register_machine(self, machine: MachineInfo):
        """Register or update a machine."""
        self.machines[machine.id] = machine
    
    def get_machine(self, machine_id: str) -> Optional[MachineInfo]:
        """Get machine by ID."""
        return self.machines.get(machine_id)
    
    def get_machine_by_name(self, name: str) -> Optional[MachineInfo]:
        """Get machine by friendly name."""
        for machine in self.machines.values():
            if machine.name.lower() == name.lower():
                return machine
        return None
    
    def list_machines(self) -> List[MachineInfo]:
        """List all registered machines."""
        return list(self.machines.values())
    
    # Project operations
    
    def register_project(self, project: ProjectInfo):
        """Register or update a project."""
        self.projects[project.name] = project
    
    def get_project(self, name: str) -> Optional[ProjectInfo]:
        """Get project by name."""
        return self.projects.get(name)
    
    def get_projects_for_machine(self, machine_id: str) -> List[ProjectInfo]:
        """Get all projects on a machine."""
        return [p for p in self.projects.values() if p.machine_id == machine_id]
    
    # Preference operations
    
    def set_preference(self, key: str, value: Any, context: Optional[str] = None):
        """Set a preference."""
        self.preferences[key] = Preference(key=key, value=value, context=context)
    
    def get_preference(self, key: str) -> Optional[Any]:
        """Get a preference value."""
        pref = self.preferences.get(key)
        return pref.value if pref else None
    
    # History operations
    
    def record_task(self, history: TaskHistory):
        """Record a task in history."""
        self.history.append(history)
        # Keep only last 1000 entries in memory
        if len(self.history) > 1000:
            self.history = self.history[-1000:]
    
    def get_recent_history(self, limit: int = 10) -> List[TaskHistory]:
        """Get recent task history."""
        return self.history[-limit:][::-1]
    
    def search_history(self, query: str) -> List[TaskHistory]:
        """Search task history."""
        query_lower = query.lower()
        return [
            h for h in self.history
            if query_lower in h.intent.lower() or query_lower in h.action.lower()
        ]


# Global memory store instance
memory = MemoryStore()
