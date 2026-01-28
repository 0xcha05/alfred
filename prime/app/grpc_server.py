"""gRPC server for daemon connections to Prime."""

import asyncio
import logging
from concurrent import futures
from datetime import datetime
from typing import Optional

import grpc
from grpc import aio

from app.config import settings
from app.core.memory import memory, MachineInfo

logger = logging.getLogger(__name__)


# We'll define a simple service for Prime that daemons connect to
# This is the reverse direction - daemons register with Prime

class PrimeServicer:
    """gRPC service for daemon registration and heartbeats."""
    
    def __init__(self):
        self.daemons: dict[str, dict] = {}
        self.daemon_counter = 0
    
    async def Register(self, request, context):
        """Handle daemon registration."""
        # Verify registration key
        metadata = dict(context.invocation_metadata())
        reg_key = metadata.get('x-registration-key', '')
        
        if reg_key != settings.daemon_registration_key:
            context.set_code(grpc.StatusCode.PERMISSION_DENIED)
            context.set_details('Invalid registration key')
            return None
        
        # Generate daemon ID
        self.daemon_counter += 1
        daemon_id = f"daemon-{self.daemon_counter:04d}"
        
        # Extract info from request (we'll use a simple dict for now)
        # In production, this would use proper protobuf messages
        daemon_info = {
            'id': daemon_id,
            'name': request.get('name', 'unknown'),
            'hostname': request.get('hostname', 'unknown'),
            'capabilities': request.get('capabilities', []),
            'address': request.get('address', ''),
            'registered_at': datetime.utcnow(),
            'last_seen': datetime.utcnow(),
            'status': 'connected',
        }
        
        self.daemons[daemon_id] = daemon_info
        
        # Also register in memory store
        memory.register_machine(MachineInfo(
            id=daemon_id,
            name=daemon_info['name'],
            hostname=daemon_info['hostname'],
            capabilities=daemon_info['capabilities'],
            last_seen=datetime.utcnow(),
            status='connected',
        ))
        
        logger.info(f"Daemon registered: {daemon_id} ({daemon_info['name']})")
        
        return {'daemon_id': daemon_id, 'success': True}
    
    async def Heartbeat(self, request, context):
        """Handle daemon heartbeat."""
        daemon_id = request.get('daemon_id', '')
        
        if daemon_id not in self.daemons:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details('Daemon not registered')
            return None
        
        self.daemons[daemon_id]['last_seen'] = datetime.utcnow()
        self.daemons[daemon_id]['status'] = 'connected'
        
        # Update memory store
        machine = memory.get_machine(daemon_id)
        if machine:
            machine.last_seen = datetime.utcnow()
            machine.status = 'connected'
        
        return {'ok': True}
    
    def get_daemon(self, daemon_id: str) -> Optional[dict]:
        """Get daemon info by ID."""
        return self.daemons.get(daemon_id)
    
    def get_daemon_by_name(self, name: str) -> Optional[dict]:
        """Get daemon info by name."""
        for daemon in self.daemons.values():
            if daemon['name'].lower() == name.lower():
                return daemon
        return None
    
    def list_daemons(self) -> list[dict]:
        """List all registered daemons."""
        return list(self.daemons.values())


# Global servicer instance
prime_servicer = PrimeServicer()


async def start_grpc_server():
    """Start the gRPC server for daemon connections."""
    server = aio.server()
    
    # Add servicer
    # Note: In a full implementation, we'd use proper generated protobuf servicers
    # For now, this is a placeholder that shows the structure
    
    # Configure TLS if certificates are available
    server_credentials = None
    try:
        if settings.tls_cert_path and settings.tls_key_path:
            import os
            if os.path.exists(settings.tls_cert_path) and os.path.exists(settings.tls_key_path):
                with open(settings.tls_key_path, 'rb') as f:
                    private_key = f.read()
                with open(settings.tls_cert_path, 'rb') as f:
                    certificate = f.read()
                server_credentials = grpc.ssl_server_credentials([(private_key, certificate)])
                logger.info("gRPC server using TLS")
    except Exception as e:
        logger.warning(f"TLS not configured: {e}")
    
    # Add port
    address = f'[::]:{settings.grpc_port}'
    if server_credentials:
        server.add_secure_port(address, server_credentials)
    else:
        server.add_insecure_port(address)
        logger.warning("gRPC server running WITHOUT TLS (development mode)")
    
    await server.start()
    logger.info(f"gRPC server started on port {settings.grpc_port}")
    
    return server
