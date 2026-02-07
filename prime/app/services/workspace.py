"""Workspace management for multi-step tasks.

Creates isolated directories for complex operations so steps don't overwrite each other.
"""

import os
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
import json

logger = logging.getLogger(__name__)

# Base directory for workspaces
WORKSPACE_BASE = Path("/home/ec2-user/ultron/data/workspaces")
WORKSPACE_BASE.mkdir(parents=True, exist_ok=True)


class Workspace:
    """An isolated workspace for a multi-step task."""
    
    def __init__(self, workspace_id: str, path: Path):
        self.id = workspace_id
        self.path = path
        self.created_at = datetime.utcnow()
        self.steps: List[Dict] = []
        self.source_files: List[str] = []
        self.current_step = 0
    
    @property
    def input_dir(self) -> Path:
        """Directory for source/input files."""
        return self.path / "input"
    
    @property
    def output_dir(self) -> Path:
        """Directory for final outputs."""
        return self.path / "output"
    
    @property
    def steps_dir(self) -> Path:
        """Directory for intermediate step results."""
        return self.path / "steps"
    
    def get_step_dir(self, step_num: int) -> Path:
        """Get directory for a specific step's output."""
        step_dir = self.steps_dir / f"step_{step_num:02d}"
        step_dir.mkdir(parents=True, exist_ok=True)
        return step_dir
    
    def add_source(self, file_path: str) -> str:
        """Copy a source file into the workspace. Returns the new path."""
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"Source file not found: {file_path}")
        
        dest = self.input_dir / src.name
        shutil.copy2(src, dest)
        self.source_files.append(str(dest))
        logger.info(f"Added source to workspace: {dest}")
        return str(dest)
    
    def record_step(self, description: str, command: str, output_files: List[str]):
        """Record a completed step."""
        self.current_step += 1
        step_record = {
            "step": self.current_step,
            "description": description,
            "command": command,
            "output_files": output_files,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.steps.append(step_record)
        self._save_state()
    
    def get_latest_file(self, pattern: str = "*") -> Optional[str]:
        """Get the most recent output file matching pattern."""
        # Check steps in reverse order
        for step in reversed(self.steps):
            for f in step.get("output_files", []):
                if Path(f).exists():
                    return f
        
        # Fall back to source files
        if self.source_files:
            return self.source_files[-1]
        
        return None
    
    def finalize(self, output_file: str) -> str:
        """Move final output to output directory."""
        src = Path(output_file)
        if not src.exists():
            raise FileNotFoundError(f"Output file not found: {output_file}")
        
        dest = self.output_dir / src.name
        shutil.copy2(src, dest)
        logger.info(f"Finalized output: {dest}")
        return str(dest)
    
    def _save_state(self):
        """Save workspace state to disk."""
        state = {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "source_files": self.source_files,
            "steps": self.steps,
            "current_step": self.current_step,
        }
        state_file = self.path / "state.json"
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)
    
    def summary(self) -> Dict:
        """Get a summary of the workspace."""
        return {
            "id": self.id,
            "path": str(self.path),
            "source_files": self.source_files,
            "steps_completed": len(self.steps),
            "current_step": self.current_step,
        }


class WorkspaceManager:
    """Manages workspaces for multi-step tasks."""
    
    def __init__(self):
        self.active_workspaces: Dict[str, Workspace] = {}
    
    def create(self, task_name: str = "task") -> Workspace:
        """Create a new workspace for a task."""
        # Generate unique ID
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        workspace_id = f"{task_name}_{timestamp}"
        
        # Create directory structure
        workspace_path = WORKSPACE_BASE / workspace_id
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "input").mkdir()
        (workspace_path / "output").mkdir()
        (workspace_path / "steps").mkdir()
        
        # Create workspace object
        workspace = Workspace(workspace_id, workspace_path)
        workspace._save_state()
        
        self.active_workspaces[workspace_id] = workspace
        logger.info(f"Created workspace: {workspace_id}")
        
        return workspace
    
    def get(self, workspace_id: str) -> Optional[Workspace]:
        """Get an existing workspace."""
        if workspace_id in self.active_workspaces:
            return self.active_workspaces[workspace_id]
        
        # Try to load from disk
        workspace_path = WORKSPACE_BASE / workspace_id
        state_file = workspace_path / "state.json"
        
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                
                workspace = Workspace(workspace_id, workspace_path)
                workspace.source_files = state.get("source_files", [])
                workspace.steps = state.get("steps", [])
                workspace.current_step = state.get("current_step", 0)
                
                self.active_workspaces[workspace_id] = workspace
                return workspace
            except Exception as e:
                logger.error(f"Failed to load workspace: {e}")
        
        return None
    
    def list_active(self) -> List[Dict]:
        """List all active workspaces."""
        return [ws.summary() for ws in self.active_workspaces.values()]
    
    def cleanup(self, workspace_id: str, keep_output: bool = True):
        """Clean up a workspace."""
        workspace = self.get(workspace_id)
        if not workspace:
            return
        
        if keep_output:
            # Only delete input and steps, keep output
            shutil.rmtree(workspace.input_dir, ignore_errors=True)
            shutil.rmtree(workspace.steps_dir, ignore_errors=True)
        else:
            # Delete entire workspace
            shutil.rmtree(workspace.path, ignore_errors=True)
        
        if workspace_id in self.active_workspaces:
            del self.active_workspaces[workspace_id]
        
        logger.info(f"Cleaned up workspace: {workspace_id}")


# Global instance
workspace_manager = WorkspaceManager()
