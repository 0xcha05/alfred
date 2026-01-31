"""
Bidirectional gRPC server for daemon connections.

Daemons connect TO Prime and maintain a persistent bidirectional stream.
This enables daemons behind NAT to work without port forwarding.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

import grpc
from grpc import aio

from app.config import settings
from app.core.memory import memory, MachineInfo

logger = logging.getLogger(__name__)


class CommandType(str, Enum):
    """Types of commands Prime can send to daemons."""
    SHELL = "shell"
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    DELETE_FILE = "delete_file"
    LIST_FILES = "list_files"
    LIST_PROCESSES = "list_processes"
    KILL_PROCESS = "kill_process"
    MANAGE_SERVICE = "manage_service"
    INSTALL_PACKAGE = "install_package"
    DOCKER = "docker"
    GIT = "git"
    SESSION = "session"
    CRON = "cron"
    SYSTEM_INFO = "system_info"
    SELF_MODIFY = "self_modify"
    PING = "ping"


@dataclass
class PendingCommand:
    """A command waiting for response from daemon."""
    command_id: str
    command_type: CommandType
    parameters: Dict[str, Any]
    created_at: datetime
    future: asyncio.Future


@dataclass
class DaemonConnection:
    """Represents a connected daemon."""
    daemon_id: str
    name: str
    hostname: str
    capabilities: list[str]
    is_soul_daemon: bool
    alfred_root: Optional[str]
    connected_at: datetime
    last_seen: datetime
    status: str
    
    # The queue for sending commands to this daemon
    command_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    
    # Pending commands waiting for response
    pending_commands: Dict[str, PendingCommand] = field(default_factory=dict)
    
    # Heartbeat info
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    active_tasks: int = 0


class DaemonRegistry:
    """
    Registry of all connected daemons.
    Manages connections and command dispatch.
    """
    
    def __init__(self):
        self.connections: Dict[str, DaemonConnection] = {}
        self.daemon_counter = 0
        self._lock = asyncio.Lock()
    
    async def register(
        self,
        registration_key: str,
        name: str,
        hostname: str,
        capabilities: list[str],
        is_soul_daemon: bool = False,
        alfred_root: Optional[str] = None,
    ) -> Optional[DaemonConnection]:
        """Register a new daemon connection."""
        
        # Verify registration key
        if registration_key != settings.daemon_registration_key:
            logger.warning(f"Registration rejected: invalid key from {name}@{hostname}")
            return None
        
        async with self._lock:
            self.daemon_counter += 1
            daemon_id = f"daemon-{self.daemon_counter:04d}"
            
            conn = DaemonConnection(
                daemon_id=daemon_id,
                name=name,
                hostname=hostname,
                capabilities=capabilities,
                is_soul_daemon=is_soul_daemon,
                alfred_root=alfred_root,
                connected_at=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                status="connected",
            )
            
            self.connections[daemon_id] = conn
            
            # Register in memory store
            memory.register_machine(MachineInfo(
                id=daemon_id,
                name=name,
                hostname=hostname,
                capabilities=capabilities,
                last_seen=datetime.utcnow(),
                status="connected",
            ))
            
            logger.info(f"Daemon registered: {daemon_id} ({name}@{hostname})")
            if is_soul_daemon:
                logger.info(f"  -> Soul daemon (can modify Alfred at {alfred_root})")
            
            return conn
    
    async def unregister(self, daemon_id: str):
        """Unregister a daemon."""
        async with self._lock:
            if daemon_id in self.connections:
                conn = self.connections.pop(daemon_id)
                logger.info(f"Daemon unregistered: {daemon_id} ({conn.name})")
                
                # Cancel any pending commands
                for cmd in conn.pending_commands.values():
                    if not cmd.future.done():
                        cmd.future.set_exception(Exception("Daemon disconnected"))
    
    def get(self, daemon_id: str) -> Optional[DaemonConnection]:
        """Get daemon connection by ID."""
        return self.connections.get(daemon_id)
    
    def get_by_name(self, name: str) -> Optional[DaemonConnection]:
        """Get daemon connection by name."""
        name_lower = name.lower()
        for conn in self.connections.values():
            if conn.name.lower() == name_lower:
                return conn
        return None
    
    def get_soul_daemon(self) -> Optional[DaemonConnection]:
        """Get the soul daemon (for self-modification)."""
        for conn in self.connections.values():
            if conn.is_soul_daemon:
                return conn
        return None
    
    def list_all(self) -> list[DaemonConnection]:
        """List all connected daemons."""
        return list(self.connections.values())
    
    def is_connected(self, daemon_id: str) -> bool:
        """Check if daemon is connected."""
        return daemon_id in self.connections
    
    async def send_command(
        self,
        daemon_id: str,
        command_type: CommandType,
        parameters: Dict[str, Any],
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """
        Send a command to a daemon and wait for the result.
        
        Returns the command result or raises an exception on timeout/error.
        """
        conn = self.connections.get(daemon_id)
        if not conn:
            raise Exception(f"Daemon {daemon_id} not connected")
        
        # Create pending command
        command_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        
        pending = PendingCommand(
            command_id=command_id,
            command_type=command_type,
            parameters=parameters,
            created_at=datetime.utcnow(),
            future=future,
        )
        
        conn.pending_commands[command_id] = pending
        
        # Build command message
        command = {
            "command_id": command_id,
            "type": command_type.value,
            **parameters,
        }
        
        # Queue the command
        await conn.command_queue.put(command)
        logger.debug(f"Command queued for {daemon_id}: {command_type.value}")
        
        try:
            # Wait for result with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.error(f"Command {command_id} timed out for {daemon_id}")
            raise Exception(f"Command timed out after {timeout}s")
        finally:
            # Clean up pending command
            conn.pending_commands.pop(command_id, None)
    
    def handle_result(self, daemon_id: str, result: Dict[str, Any]):
        """Handle a command result from a daemon."""
        conn = self.connections.get(daemon_id)
        if not conn:
            logger.warning(f"Result from unknown daemon: {daemon_id}")
            return
        
        command_id = result.get("command_id")
        if not command_id:
            logger.warning(f"Result without command_id from {daemon_id}")
            return
        
        pending = conn.pending_commands.get(command_id)
        if not pending:
            logger.warning(f"Result for unknown command {command_id} from {daemon_id}")
            return
        
        if not pending.future.done():
            pending.future.set_result(result)
            logger.debug(f"Command {command_id} completed for {daemon_id}")
    
    def handle_heartbeat(self, daemon_id: str, heartbeat: Dict[str, Any]):
        """Handle a heartbeat from a daemon."""
        conn = self.connections.get(daemon_id)
        if not conn:
            return
        
        conn.last_seen = datetime.utcnow()
        conn.cpu_percent = heartbeat.get("cpu_percent", 0.0)
        conn.memory_percent = heartbeat.get("memory_percent", 0.0)
        conn.disk_percent = heartbeat.get("disk_percent", 0.0)
        conn.active_tasks = heartbeat.get("active_tasks", 0)
    
    def handle_alert(self, daemon_id: str, alert: Dict[str, Any]):
        """Handle an alert from a daemon."""
        conn = self.connections.get(daemon_id)
        name = conn.name if conn else daemon_id
        
        alert_type = alert.get("alert_type", "unknown")
        message = alert.get("message", "")
        severity = alert.get("severity", "info")
        
        log_fn = logger.info
        if severity == "warning":
            log_fn = logger.warning
        elif severity in ("error", "critical"):
            log_fn = logger.error
        
        log_fn(f"Alert from {name}: [{alert_type}] {message}")
        
        # TODO: Forward to notification system (Telegram, etc.)
    
    async def handle_daemon_event(self, daemon_id: str, event_data: Dict[str, Any]):
        """Handle a proactive event from a daemon.
        
        Daemon events are routed to the event bus for processing by the brain.
        """
        from app.core.events import Event, event_bus
        
        conn = self.connections.get(daemon_id)
        daemon_name = conn.name if conn else daemon_id
        
        source = event_data.get("source", f"daemon:{daemon_name}")
        event_type = event_data.get("event_type", "alert")
        payload = event_data.get("payload", {})
        
        logger.info(f"Daemon event from {daemon_name}: {source}/{event_type}")
        
        # Create an Event and publish to the bus
        # The context should include where to respond (we'll use the first allowed telegram user for now)
        from app.config import settings
        
        context = {}
        if settings.telegram_allowed_user_ids:
            # Send to the first allowed user
            context["chat_id"] = settings.telegram_allowed_user_ids[0]
        
        event = Event(
            source=source,
            type=event_type,
            payload=payload,
            context=context,
        )
        
        await event_bus.publish(event)


# Global registry instance
daemon_registry = DaemonRegistry()


class PrimeServicer:
    """
    gRPC servicer for PrimeService.
    Handles bidirectional streaming connections from daemons.
    """
    
    def __init__(self, registry: DaemonRegistry):
        self.registry = registry
    
    async def Connect(self, request_iterator, context):
        """
        Handle bidirectional streaming connection from a daemon.
        
        Protocol:
        1. Daemon sends Registration message first
        2. Prime responds with RegistrationAck
        3. Then bidirectional: daemon sends heartbeats/results, Prime sends commands
        """
        daemon_id = None
        daemon_conn = None
        
        try:
            # Process incoming messages
            async for message in request_iterator:
                msg_type = message.get("type")
                
                # Handle registration (must be first message)
                if msg_type == "registration":
                    if daemon_id:
                        logger.warning("Duplicate registration attempt")
                        continue
                    
                    daemon_conn = await self.registry.register(
                        registration_key=message.get("registration_key", ""),
                        name=message.get("name", "unknown"),
                        hostname=message.get("hostname", "unknown"),
                        capabilities=message.get("capabilities", []),
                        is_soul_daemon=message.get("is_soul_daemon", False),
                        alfred_root=message.get("alfred_root"),
                    )
                    
                    if daemon_conn:
                        daemon_id = daemon_conn.daemon_id
                        
                        # Send registration ack
                        yield {
                            "command_id": "",
                            "type": "registration_ack",
                            "success": True,
                            "daemon_id": daemon_id,
                            "message": f"Welcome, {daemon_conn.name}!",
                        }
                        
                        # Start command sender task
                        asyncio.create_task(
                            self._send_commands(daemon_conn, context)
                        )
                    else:
                        yield {
                            "command_id": "",
                            "type": "registration_ack",
                            "success": False,
                            "daemon_id": "",
                            "message": "Registration failed - invalid key",
                        }
                        return
                
                # Handle heartbeat
                elif msg_type == "heartbeat":
                    if daemon_id:
                        self.registry.handle_heartbeat(daemon_id, message)
                
                # Handle command result
                elif msg_type == "result":
                    if daemon_id:
                        self.registry.handle_result(daemon_id, message)
                
                # Handle alert
                elif msg_type == "alert":
                    if daemon_id:
                        self.registry.handle_alert(daemon_id, message)
                
                # Handle daemon event (proactive events from daemon)
                elif msg_type == "event":
                    if daemon_id:
                        await self.registry.handle_daemon_event(daemon_id, message)
                
                else:
                    logger.warning(f"Unknown message type: {msg_type}")
        
        except Exception as e:
            logger.error(f"Connection error for {daemon_id}: {e}")
        
        finally:
            # Clean up on disconnect
            if daemon_id:
                await self.registry.unregister(daemon_id)
    
    async def _send_commands(self, conn: DaemonConnection, context):
        """Send commands from the queue to the daemon."""
        try:
            while not context.done():
                try:
                    # Get next command with timeout (for checking context.done())
                    command = await asyncio.wait_for(
                        conn.command_queue.get(), 
                        timeout=1.0
                    )
                    
                    # Yield command to the stream
                    # Note: This is a bit tricky in gRPC - we need to yield from Connect()
                    # For now, we'll use a different approach with async generators
                    
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            logger.error(f"Command sender error for {conn.daemon_id}: {e}")


# Alternative simpler implementation using a message protocol over the stream
class SimplePrimeServicer:
    """
    Simplified servicer that uses JSON-like messages over the stream.
    This is easier to implement without full protobuf code generation.
    """
    
    def __init__(self, registry: DaemonRegistry):
        self.registry = registry


async def handle_daemon_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
):
    """
    Handle a daemon connection using raw TCP with JSON messages.
    This is a simpler alternative to gRPC that works without protobuf generation.
    """
    import json
    
    daemon_id = None
    daemon_conn = None
    peer = writer.get_extra_info('peername')
    logger.info(f"New connection from {peer}")
    
    try:
        while True:
            # Read message length (4 bytes, big-endian)
            length_bytes = await reader.readexactly(4)
            length = int.from_bytes(length_bytes, 'big')
            
            # Read message
            data = await reader.readexactly(length)
            message = json.loads(data.decode('utf-8'))
            
            msg_type = message.get("type")
            
            # Handle registration
            if msg_type == "registration":
                daemon_conn = await daemon_registry.register(
                    registration_key=message.get("registration_key", ""),
                    name=message.get("name", "unknown"),
                    hostname=message.get("hostname", "unknown"),
                    capabilities=message.get("capabilities", []),
                    is_soul_daemon=message.get("is_soul_daemon", False),
                    alfred_root=message.get("alfred_root"),
                )
                
                if daemon_conn:
                    daemon_id = daemon_conn.daemon_id
                    response = {
                        "type": "registration_ack",
                        "success": True,
                        "daemon_id": daemon_id,
                        "message": f"Welcome, {daemon_conn.name}!",
                    }
                    
                    # Start command sender
                    asyncio.create_task(_command_sender(daemon_conn, writer))
                else:
                    response = {
                        "type": "registration_ack",
                        "success": False,
                        "message": "Invalid registration key",
                    }
                
                await _send_message(writer, response)
                
                if not daemon_conn:
                    break
            
            # Handle heartbeat
            elif msg_type == "heartbeat":
                if daemon_id:
                    daemon_registry.handle_heartbeat(daemon_id, message)
            
            # Handle result
            elif msg_type == "result":
                if daemon_id:
                    daemon_registry.handle_result(daemon_id, message)
            
            # Handle alert
            elif msg_type == "alert":
                if daemon_id:
                    daemon_registry.handle_alert(daemon_id, message)
    
    except asyncio.IncompleteReadError:
        logger.info(f"Connection closed by {peer}")
    except Exception as e:
        logger.error(f"Connection error from {peer}: {e}")
    finally:
        if daemon_id:
            await daemon_registry.unregister(daemon_id)
        writer.close()
        await writer.wait_closed()


async def _send_message(writer: asyncio.StreamWriter, message: dict):
    """Send a JSON message with length prefix."""
    import json
    data = json.dumps(message).encode('utf-8')
    length = len(data).to_bytes(4, 'big')
    writer.write(length + data)
    await writer.drain()


async def _command_sender(conn: DaemonConnection, writer: asyncio.StreamWriter):
    """Send queued commands to the daemon."""
    try:
        while True:
            command = await conn.command_queue.get()
            await _send_message(writer, command)
    except Exception as e:
        logger.error(f"Command sender error for {conn.daemon_id}: {e}")


async def start_daemon_server(host: str = "0.0.0.0", port: int = 50051):
    """Start the TCP server for daemon connections."""
    server = await asyncio.start_server(
        handle_daemon_connection,
        host,
        port,
    )
    
    addr = server.sockets[0].getsockname()
    logger.info(f"Daemon server listening on {addr[0]}:{addr[1]}")
    
    return server


def resolve_daemon(daemon_id_or_name: str) -> str:
    """Resolve a daemon name or ID to an actual daemon_id.
    
    Accepts:
    - daemon_id (e.g., "daemon-0001") - returned as-is
    - daemon name (e.g., "macbook") - looked up and daemon_id returned
    """
    logger.debug(f"resolve_daemon called with: {daemon_id_or_name}")
    
    # If it looks like a daemon_id, use it directly
    if daemon_id_or_name.startswith("daemon-"):
        return daemon_id_or_name
    
    # Otherwise, look up by name
    conn = daemon_registry.get_by_name(daemon_id_or_name)
    logger.debug(f"get_by_name result: {conn}")
    
    if conn:
        logger.debug(f"Resolved {daemon_id_or_name} -> {conn.daemon_id}")
        return conn.daemon_id
    
    # List all connected daemons for debugging
    all_daemons = daemon_registry.list_all()
    logger.warning(f"Daemon '{daemon_id_or_name}' not found. Connected daemons: {[(d.daemon_id, d.name) for d in all_daemons]}")
    
    # Not found
    raise Exception(f"Daemon {daemon_id_or_name} not connected")


# Convenience functions for sending commands
async def execute_shell(
    daemon_id_or_name: str,
    command: str,
    working_directory: str = "",
    timeout: float = 60.0,
    use_sudo: bool = False,
) -> Dict[str, Any]:
    """Execute a shell command on a daemon."""
    daemon_id = resolve_daemon(daemon_id_or_name)
    return await daemon_registry.send_command(
        daemon_id,
        CommandType.SHELL,
        {
            "command": command,
            "working_directory": working_directory,
            "use_sudo": use_sudo,
        },
        timeout=timeout,
    )


async def read_file(daemon_id_or_name: str, path: str) -> Dict[str, Any]:
    """Read a file from a daemon."""
    daemon_id = resolve_daemon(daemon_id_or_name)
    return await daemon_registry.send_command(
        daemon_id,
        CommandType.READ_FILE,
        {"path": path},
    )


async def write_file(
    daemon_id_or_name: str,
    path: str,
    content: bytes,
    create_dirs: bool = True,
) -> Dict[str, Any]:
    """Write a file on a daemon."""
    daemon_id = resolve_daemon(daemon_id_or_name)
    import base64
    return await daemon_registry.send_command(
        daemon_id,
        CommandType.WRITE_FILE,
        {
            "path": path,
            "content": base64.b64encode(content).decode('ascii'),
            "create_dirs": create_dirs,
        },
    )


async def list_files(
    daemon_id_or_name: str,
    path: str,
    recursive: bool = False,
) -> Dict[str, Any]:
    """List files on a daemon."""
    daemon_id = resolve_daemon(daemon_id_or_name)
    return await daemon_registry.send_command(
        daemon_id,
        CommandType.LIST_FILES,
        {"path": path, "recursive": recursive},
    )


async def get_system_info(daemon_id: str) -> Dict[str, Any]:
    """Get system info from a daemon."""
    return await daemon_registry.send_command(
        daemon_id,
        CommandType.SYSTEM_INFO,
        {},
    )


async def docker_command(
    daemon_id: str,
    args: list[str],
    working_directory: str = "",
) -> Dict[str, Any]:
    """Run a docker command on a daemon."""
    return await daemon_registry.send_command(
        daemon_id,
        CommandType.DOCKER,
        {"args": args, "working_directory": working_directory},
    )


async def git_command(
    daemon_id: str,
    args: list[str],
    working_directory: str = "",
) -> Dict[str, Any]:
    """Run a git command on a daemon."""
    return await daemon_registry.send_command(
        daemon_id,
        CommandType.GIT,
        {"args": args, "working_directory": working_directory},
    )


async def send_command(
    daemon_id_or_name: str,
    command_type: str,
    params: Dict[str, Any] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """
    Send a generic command to a daemon.
    
    This allows sending any command type (including browser_* commands)
    without needing to add them to the CommandType enum.
    """
    logger.info(f"send_command called: {command_type} to {daemon_id_or_name}")
    
    daemon_id = resolve_daemon(daemon_id_or_name)
    logger.info(f"Resolved to daemon_id: {daemon_id}")
    
    # Use string command type directly instead of enum
    # This bypasses the CommandType enum for custom commands
    conn = daemon_registry.connections.get(daemon_id)
    if not conn:
        logger.error(f"Daemon {daemon_id} not in connections")
        raise Exception(f"Daemon {daemon_id} not connected")
    
    command_id = str(uuid.uuid4())
    command = {
        "type": command_type,
        "id": command_id,
        "params": params or {},
    }
    
    logger.info(f"Sending command {command_id}: {command_type}")
    
    # Create pending command entry
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    pending = PendingCommand(
        command_id=command_id,
        command_type=CommandType.SHELL,  # Placeholder for custom types
        parameters=params or {},
        created_at=datetime.utcnow(),
        future=future,
    )
    conn.pending_commands[command_id] = pending
    
    # Put command in queue
    await conn.command_queue.put(command)
    logger.info(f"Command {command_id} queued, waiting for response...")
    
    # Wait for response via future
    try:
        result = await asyncio.wait_for(pending.future, timeout=timeout)
        logger.info(f"Command {command_id} completed: {result}")
        return result or {}
    except asyncio.TimeoutError:
        logger.error(f"Command {command_id} timed out after {timeout}s")
        return {"error": f"Command timed out after {timeout}s"}
    finally:
        conn.pending_commands.pop(command_id, None)
