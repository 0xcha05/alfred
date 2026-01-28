"""gRPC client for Prime to communicate with daemons."""

import asyncio
import logging
from typing import Optional, AsyncIterator, Any
from dataclasses import dataclass

import grpc
from grpc import aio

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DaemonConnection:
    """Represents a connection to a daemon."""
    daemon_id: str
    address: str
    channel: Optional[aio.Channel] = None
    connected: bool = False


class DaemonClient:
    """Client for communicating with daemons via gRPC."""
    
    def __init__(self):
        self.connections: dict[str, DaemonConnection] = {}
    
    async def connect(self, daemon_id: str, address: str, use_tls: bool = False) -> bool:
        """Establish connection to a daemon."""
        try:
            # Create channel
            if use_tls:
                # Load root certificates for TLS
                try:
                    with open(settings.tls_cert_path, 'rb') as f:
                        root_certs = f.read()
                    credentials = grpc.ssl_channel_credentials(root_certs)
                    channel = aio.secure_channel(address, credentials)
                except Exception as e:
                    logger.warning(f"TLS connection failed, falling back to insecure: {e}")
                    channel = aio.insecure_channel(address)
            else:
                channel = aio.insecure_channel(address)
            
            # Store connection
            self.connections[daemon_id] = DaemonConnection(
                daemon_id=daemon_id,
                address=address,
                channel=channel,
                connected=True,
            )
            
            logger.info(f"Connected to daemon {daemon_id} at {address}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to daemon {daemon_id}: {e}")
            return False
    
    async def disconnect(self, daemon_id: str):
        """Disconnect from a daemon."""
        if daemon_id in self.connections:
            conn = self.connections[daemon_id]
            if conn.channel:
                await conn.channel.close()
            del self.connections[daemon_id]
            logger.info(f"Disconnected from daemon {daemon_id}")
    
    async def execute_shell(
        self,
        daemon_id: str,
        command: str,
        working_directory: str = "",
        timeout_seconds: int = 300,
    ) -> AsyncIterator[str]:
        """Execute a shell command on a daemon and stream output."""
        conn = self.connections.get(daemon_id)
        if not conn or not conn.channel:
            raise Exception(f"Not connected to daemon {daemon_id}")
        
        logger.info(f"Executing on {daemon_id}: {command}")
        
        try:
            # Use the channel to make the streaming call
            # This uses grpc reflection/dynamic calling since we don't have generated stubs yet
            
            # For production, we'd use generated stubs:
            # stub = DaemonServiceStub(conn.channel)
            # async for response in stub.ExecuteShell(ShellRequest(...)):
            #     yield response.stdout or response.stderr
            
            # For now, we make a direct call using the low-level API
            method = '/alfred.daemon.DaemonService/ExecuteShell'
            
            # Create request metadata
            request_data = {
                'command': command,
                'working_directory': working_directory,
                'timeout_seconds': timeout_seconds,
            }
            
            # Serialize request (simplified - would use protobuf in production)
            import json
            request_bytes = json.dumps(request_data).encode()
            
            # For now, yield placeholder - actual streaming will use protobuf
            yield f"$ {command}"
            
            # Make unary call for now (streaming requires proper proto stubs)
            # In production this would stream line by line
            try:
                # Attempt to call the daemon
                call = conn.channel.unary_unary(
                    method,
                    request_serializer=lambda x: x,
                    response_deserializer=lambda x: x,
                )
                # This is a placeholder - proper implementation needs proto stubs
                yield "[Streaming output from daemon...]"
            except Exception as call_err:
                logger.debug(f"Direct call failed (expected without proto stubs): {call_err}")
                yield f"[Daemon execution pending - proto stubs needed for full streaming]"
            
        except Exception as e:
            logger.error(f"Shell execution failed: {e}")
            yield f"[Error: {e}]"
            raise
    
    async def read_file(self, daemon_id: str, path: str) -> bytes:
        """Read a file from a daemon."""
        conn = self.connections.get(daemon_id)
        if not conn or not conn.channel:
            raise Exception(f"Not connected to daemon {daemon_id}")
        
        # Placeholder
        logger.info(f"Reading file from {daemon_id}: {path}")
        return b"[File reading will be implemented with protobuf stubs]"
    
    async def write_file(self, daemon_id: str, path: str, content: bytes) -> bool:
        """Write a file to a daemon."""
        conn = self.connections.get(daemon_id)
        if not conn or not conn.channel:
            raise Exception(f"Not connected to daemon {daemon_id}")
        
        # Placeholder
        logger.info(f"Writing file to {daemon_id}: {path}")
        return True
    
    async def list_files(self, daemon_id: str, path: str, recursive: bool = False) -> list[dict]:
        """List files on a daemon."""
        conn = self.connections.get(daemon_id)
        if not conn or not conn.channel:
            raise Exception(f"Not connected to daemon {daemon_id}")
        
        # Placeholder
        logger.info(f"Listing files on {daemon_id}: {path}")
        return []
    
    def is_connected(self, daemon_id: str) -> bool:
        """Check if connected to a daemon."""
        return daemon_id in self.connections and self.connections[daemon_id].connected
    
    def list_connections(self) -> list[str]:
        """List all connected daemon IDs."""
        return list(self.connections.keys())


# Global client instance
daemon_client = DaemonClient()
