"""Task model for tracking execution history."""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, Integer, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.models.base import Base


class Task(Base):
    """Represents a task execution record."""
    
    __tablename__ = "tasks"
    
    id = Column(String, primary_key=True)
    
    # Association
    machine_id = Column(String, ForeignKey("machines.id"), nullable=True)
    
    # Task details
    action = Column(String, nullable=False)  # shell, read_file, etc.
    parameters = Column(JSON, default=dict)
    
    # Execution
    status = Column(String, default="pending")  # pending, running, completed, failed, cancelled
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    exit_code = Column(Integer, nullable=True)
    
    # Timing
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    
    # Context
    intent = Column(Text, nullable=True)  # Original user message
    
    def __repr__(self):
        return f"<Task {self.id}: {self.action} ({self.status})>"
    
    def to_dict(self):
        return {
            "id": self.id,
            "machine_id": self.machine_id,
            "action": self.action,
            "parameters": self.parameters,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
        }
