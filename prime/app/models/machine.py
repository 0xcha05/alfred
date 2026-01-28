"""Machine/Daemon model."""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, Boolean, Integer
from sqlalchemy.dialects.postgresql import ARRAY

from app.models.base import Base, TimestampMixin


class Machine(Base, TimestampMixin):
    """Represents a registered daemon/machine."""
    
    __tablename__ = "machines"
    
    id = Column(String, primary_key=True)  # e.g., "daemon-0001"
    name = Column(String, nullable=False)  # Friendly name
    hostname = Column(String, nullable=False)
    grpc_address = Column(String, nullable=False)  # host:port for gRPC
    
    # Capabilities
    capabilities = Column(ARRAY(String), default=list)  # ["shell", "files", "browser"]
    
    # Status
    status = Column(String, default="registered")  # registered, connected, disconnected
    last_seen = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # Metadata
    metadata_ = Column("metadata", JSON, default=dict)  # OS info, resources, etc.
    
    # Priority for routing (lower = higher priority)
    priority = Column(Integer, default=100)
    
    def __repr__(self):
        return f"<Machine {self.id}: {self.name} ({self.status})>"
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "hostname": self.hostname,
            "grpc_address": self.grpc_address,
            "capabilities": self.capabilities or [],
            "status": self.status,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "is_active": self.is_active,
            "priority": self.priority,
        }
