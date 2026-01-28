"""Daemon communication endpoints (REST for registration, gRPC for commands)."""

import logging
from fastapi import APIRouter, HTTPException, Header, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from app.config import settings
from app.core.memory import memory, MachineInfo
from app.core.router import router as task_router
from app.grpc_client import daemon_client

logger = logging.getLogger(__name__)

router = APIRouter()


# In-memory daemon registry (will be moved to database)
connected_daemons: dict = {}
daemon_counter = 0


class DaemonRegistration(BaseModel):
    """Daemon registration request."""
    name: str
    hostname: str
    capabilities: List[str]
    grpc_address: str  # Address where daemon's gRPC server is listening
    is_soul_daemon: bool = False  # True if this is the daemon on Prime's server
    alfred_root: Optional[str] = None  # Root directory of Alfred installation (for soul daemon)


class DaemonInfo(BaseModel):
    """Daemon information."""
    id: str
    name: str
    hostname: str
    capabilities: List[str]
    grpc_address: str
    last_seen: datetime
    status: str


async def connect_to_daemon(daemon_id: str, address: str):
    """Background task to connect to daemon's gRPC server."""
    try:
        success = await daemon_client.connect(daemon_id, address, use_tls=False)
        if success:
            connected_daemons[daemon_id]["status"] = "connected"
            logger.info(f"gRPC connection established to {daemon_id}")
        else:
            connected_daemons[daemon_id]["status"] = "connection_failed"
    except Exception as e:
        logger.error(f"Failed to connect to daemon {daemon_id}: {e}")
        connected_daemons[daemon_id]["status"] = "connection_failed"


@router.post("/register")
async def register_daemon(
    registration: DaemonRegistration,
    background_tasks: BackgroundTasks,
    x_registration_key: str = Header(...),
):
    """Register a new daemon."""
    global daemon_counter
    
    # Verify registration key
    if settings.daemon_registration_key and x_registration_key != settings.daemon_registration_key:
        raise HTTPException(status_code=403, detail="Invalid registration key")
    
    # Generate daemon ID
    daemon_counter += 1
    daemon_id = f"daemon-{daemon_counter:04d}"
    
    # Store daemon info
    daemon_info = {
        "id": daemon_id,
        "name": registration.name,
        "hostname": registration.hostname,
        "capabilities": registration.capabilities,
        "grpc_address": registration.grpc_address,
        "is_soul_daemon": registration.is_soul_daemon,
        "alfred_root": registration.alfred_root,
        "last_seen": datetime.utcnow(),
        "status": "registering",
    }
    connected_daemons[daemon_id] = daemon_info
    
    if registration.is_soul_daemon:
        logger.info(f"Soul daemon registered: {daemon_id} (Alfred root: {registration.alfred_root})")
    
    # Register in memory store
    memory.register_machine(MachineInfo(
        id=daemon_id,
        name=registration.name,
        hostname=registration.hostname,
        capabilities=registration.capabilities,
        last_seen=datetime.utcnow(),
        status="registering",
    ))
    
    # Register in task router
    task_router.register_daemon(daemon_id, daemon_info)
    
    # Connect to daemon's gRPC server in background
    background_tasks.add_task(connect_to_daemon, daemon_id, registration.grpc_address)
    
    logger.info(f"Daemon registered: {daemon_id} ({registration.name}) at {registration.grpc_address}")
    
    return {
        "daemon_id": daemon_id,
        "message": f"Welcome, {registration.name}",
    }


@router.get("/list")
async def list_daemons():
    """List all connected daemons."""
    daemons = []
    for d in connected_daemons.values():
        daemons.append({
            **d,
            "last_seen": d["last_seen"].isoformat() if isinstance(d["last_seen"], datetime) else d["last_seen"],
        })
    
    return {
        "daemons": daemons,
        "count": len(daemons),
    }


@router.get("/{daemon_id}")
async def get_daemon(daemon_id: str):
    """Get information about a specific daemon."""
    if daemon_id not in connected_daemons:
        raise HTTPException(status_code=404, detail="Daemon not found")
    
    d = connected_daemons[daemon_id]
    return {
        **d,
        "last_seen": d["last_seen"].isoformat() if isinstance(d["last_seen"], datetime) else d["last_seen"],
        "grpc_connected": daemon_client.is_connected(daemon_id),
    }


@router.post("/{daemon_id}/heartbeat")
async def daemon_heartbeat(
    daemon_id: str,
    x_registration_key: str = Header(...),
):
    """Update daemon heartbeat."""
    if settings.daemon_registration_key and x_registration_key != settings.daemon_registration_key:
        raise HTTPException(status_code=403, detail="Invalid registration key")
    
    if daemon_id not in connected_daemons:
        raise HTTPException(status_code=404, detail="Daemon not found")
    
    connected_daemons[daemon_id]["last_seen"] = datetime.utcnow()
    connected_daemons[daemon_id]["status"] = "connected"
    
    # Update memory store
    machine = memory.get_machine(daemon_id)
    if machine:
        machine.last_seen = datetime.utcnow()
        machine.status = "connected"
    
    return {"ok": True}


@router.delete("/{daemon_id}")
async def unregister_daemon(
    daemon_id: str,
    x_registration_key: str = Header(...),
):
    """Unregister a daemon."""
    if settings.daemon_registration_key and x_registration_key != settings.daemon_registration_key:
        raise HTTPException(status_code=403, detail="Invalid registration key")
    
    if daemon_id not in connected_daemons:
        raise HTTPException(status_code=404, detail="Daemon not found")
    
    # Disconnect gRPC
    await daemon_client.disconnect(daemon_id)
    
    # Remove from registries
    del connected_daemons[daemon_id]
    task_router.unregister_daemon(daemon_id)
    
    logger.info(f"Daemon unregistered: {daemon_id}")
    
    return {"ok": True, "message": f"Daemon {daemon_id} unregistered"}
