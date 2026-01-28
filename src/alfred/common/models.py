"""Shared data models for Alfred Prime and Daemons."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Status of a task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Capability(str, Enum):
    """Daemon capabilities."""

    SHELL = "shell"
    FILES = "files"
    BROWSER = "browser"
    DOCKER = "docker"
    SERVICES = "services"


class PermissionTier(str, Enum):
    """Permission levels for actions."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SENSITIVE = "sensitive"
    DESTRUCTIVE = "destructive"


class DaemonInfo(BaseModel):
    """Information about a registered daemon."""

    name: str = Field(..., description="Unique daemon identifier")
    machine_type: str = Field(..., description="Type of machine")
    capabilities: list[Capability] = Field(
        default_factory=list, description="Enabled capabilities"
    )
    hostname: str = Field(..., description="Machine hostname")
    ip_address: str = Field(..., description="IP address")
    port: int = Field(..., description="Daemon API port")
    online: bool = Field(default=True, description="Whether daemon is online")
    last_seen: datetime = Field(
        default_factory=datetime.utcnow, description="Last heartbeat time"
    )


class TaskRequest(BaseModel):
    """A task to be executed by a daemon."""

    task_id: str = Field(..., description="Unique task identifier")
    action: str = Field(..., description="Action type (shell, read_file, etc.)")
    params: dict[str, Any] = Field(
        default_factory=dict, description="Action parameters"
    )
    timeout: int = Field(default=300, description="Timeout in seconds")
    permission_tier: PermissionTier = Field(
        default=PermissionTier.READ, description="Required permission level"
    )


class TaskResult(BaseModel):
    """Result of a task execution."""

    task_id: str = Field(..., description="Task identifier")
    status: TaskStatus = Field(..., description="Execution status")
    output: str | None = Field(default=None, description="Command output")
    error: str | None = Field(default=None, description="Error message if failed")
    exit_code: int | None = Field(default=None, description="Exit code for shell commands")
    started_at: datetime = Field(
        default_factory=datetime.utcnow, description="Start time"
    )
    completed_at: datetime | None = Field(default=None, description="Completion time")
    data: dict[str, Any] = Field(
        default_factory=dict, description="Additional result data"
    )


class Message(BaseModel):
    """A message in the conversation."""

    role: str = Field(..., description="Message role (user/assistant)")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Message timestamp"
    )
    channel: str = Field(default="telegram", description="Message channel")
    user_id: str | None = Field(default=None, description="User identifier")
