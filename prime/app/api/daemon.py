"""
Daemon management endpoints.

NOTE: Daemons now connect via bidirectional TCP to port 50051.
These REST endpoints are for monitoring and management only.
"""

import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


class DaemonInfo(BaseModel):
    """Daemon information."""
    id: str
    name: str
    hostname: str
    capabilities: List[str]
    is_soul_daemon: bool
    connected_at: str
    last_seen: str
    status: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    active_tasks: int


@router.get("/list")
async def list_daemons(request: Request):
    """List all connected daemons."""
    # Get registry from app state
    registry = getattr(request.app.state, 'daemon_registry', None)
    if not registry:
        return {"daemons": [], "count": 0, "error": "Registry not initialized"}
    
    daemons = []
    for conn in registry.list_all():
        daemons.append({
            "id": conn.daemon_id,
            "name": conn.name,
            "hostname": conn.hostname,
            "capabilities": conn.capabilities,
            "is_soul_daemon": conn.is_soul_daemon,
            "connected_at": conn.connected_at.isoformat(),
            "last_seen": conn.last_seen.isoformat(),
            "status": conn.status,
            "cpu_percent": conn.cpu_percent,
            "memory_percent": conn.memory_percent,
            "disk_percent": conn.disk_percent,
            "active_tasks": conn.active_tasks,
        })
    
    return {
        "daemons": daemons,
        "count": len(daemons),
    }


@router.get("/{daemon_id}")
async def get_daemon(daemon_id: str, request: Request):
    """Get information about a specific daemon."""
    registry = getattr(request.app.state, 'daemon_registry', None)
    if not registry:
        raise HTTPException(status_code=500, detail="Registry not initialized")
    
    conn = registry.get(daemon_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Daemon not found")
    
    return {
        "id": conn.daemon_id,
        "name": conn.name,
        "hostname": conn.hostname,
        "capabilities": conn.capabilities,
        "is_soul_daemon": conn.is_soul_daemon,
        "alfred_root": conn.alfred_root,
        "connected_at": conn.connected_at.isoformat(),
        "last_seen": conn.last_seen.isoformat(),
        "status": conn.status,
        "cpu_percent": conn.cpu_percent,
        "memory_percent": conn.memory_percent,
        "disk_percent": conn.disk_percent,
        "active_tasks": conn.active_tasks,
        "pending_commands": len(conn.pending_commands),
    }


@router.get("/by-name/{name}")
async def get_daemon_by_name(name: str, request: Request):
    """Get daemon by name."""
    registry = getattr(request.app.state, 'daemon_registry', None)
    if not registry:
        raise HTTPException(status_code=500, detail="Registry not initialized")
    
    conn = registry.get_by_name(name)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Daemon '{name}' not found")
    
    return {
        "id": conn.daemon_id,
        "name": conn.name,
        "hostname": conn.hostname,
        "status": conn.status,
    }


@router.get("/soul")
async def get_soul_daemon(request: Request):
    """Get the soul daemon (for self-modification)."""
    registry = getattr(request.app.state, 'daemon_registry', None)
    if not registry:
        raise HTTPException(status_code=500, detail="Registry not initialized")
    
    conn = registry.get_soul_daemon()
    if not conn:
        raise HTTPException(status_code=404, detail="No soul daemon connected")
    
    return {
        "id": conn.daemon_id,
        "name": conn.name,
        "alfred_root": conn.alfred_root,
        "status": conn.status,
    }


class CommandRequest(BaseModel):
    """Request to execute a command on a daemon."""
    command: str
    working_directory: str = ""
    timeout: float = 60.0
    use_sudo: bool = False


@router.post("/{daemon_id}/execute")
async def execute_command(daemon_id: str, cmd: CommandRequest, request: Request):
    """Execute a shell command on a daemon."""
    registry = getattr(request.app.state, 'daemon_registry', None)
    if not registry:
        raise HTTPException(status_code=500, detail="Registry not initialized")
    
    if not registry.is_connected(daemon_id):
        raise HTTPException(status_code=404, detail=f"Daemon {daemon_id} not connected")
    
    try:
        from app.grpc_server import execute_shell
        result = await execute_shell(
            daemon_id=daemon_id,
            command=cmd.command,
            working_directory=cmd.working_directory,
            timeout=cmd.timeout,
            use_sudo=cmd.use_sudo,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{daemon_id}/ping")
async def ping_daemon(daemon_id: str, request: Request):
    """Ping a daemon to check connectivity."""
    registry = getattr(request.app.state, 'daemon_registry', None)
    if not registry:
        raise HTTPException(status_code=500, detail="Registry not initialized")
    
    conn = registry.get(daemon_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Daemon not found")
    
    # Check last heartbeat
    from datetime import timedelta
    now = datetime.utcnow()
    age = now - conn.last_seen
    
    return {
        "daemon_id": daemon_id,
        "name": conn.name,
        "status": conn.status,
        "last_seen": conn.last_seen.isoformat(),
        "age_seconds": age.total_seconds(),
        "healthy": age < timedelta(minutes=2),
    }


@router.get("/connection-info")
async def connection_info(request: Request):
    """Get connection information for daemons."""
    return {
        "host": "0.0.0.0",
        "port": settings.daemon_port,
        "protocol": "tcp+json",
        "registration_key_required": bool(settings.daemon_registration_key),
        "message": f"Daemons should connect to port {settings.daemon_port} using bidirectional TCP",
    }
