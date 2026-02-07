"""Project model for machine-project associations."""

from sqlalchemy import Column, String, JSON, ForeignKey
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    """Represents a project registered with Ultron."""
    
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True)  # e.g., "myapp"
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    
    # Machine association
    machine_id = Column(String, ForeignKey("machines.id"), nullable=False)
    path = Column(String, nullable=False)  # Path on the machine
    
    # Commands
    commands = Column(JSON, default=dict)  # {"test": "npm test", "build": "npm build", ...}
    
    # Environment
    environment = Column(JSON, default=dict)  # {"NODE_ENV": "development", ...}
    
    def __repr__(self):
        return f"<Project {self.name} on {self.machine_id}>"
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "machine_id": self.machine_id,
            "path": self.path,
            "commands": self.commands or {},
            "environment": self.environment or {},
        }
