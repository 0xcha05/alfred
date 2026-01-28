"""Task routing to appropriate daemons."""

import logging
import re
from typing import Optional, List
from app.core.intent import ParsedIntent, ActionType

logger = logging.getLogger(__name__)

# Actions that should be routed to the soul daemon (on Prime's server)
SOUL_DAEMON_ACTIONS = {
    ActionType.MODIFY_CODE,
    ActionType.CREATE_CODE,
    ActionType.REBUILD,
    ActionType.RESTART,
    ActionType.UPDATE_DEPS,
}


class TaskRouter:
    """Routes tasks to appropriate daemons based on intent and capabilities."""
    
    def __init__(self):
        # Will be populated from database and daemon registrations
        self.machine_registry: dict = {}
        self.project_mappings: dict = {}  # project_name -> machine_id
        self.aliases: dict = {}  # alias -> machine_id (e.g., "macbook" -> "daemon-0001")
    
    def get_target_daemon(self, intent: ParsedIntent) -> Optional[str]:
        """Determine which daemon should execute this intent."""
        
        # Self-modification actions go to soul daemon
        if intent.action in SOUL_DAEMON_ACTIONS:
            soul_daemon = self._get_soul_daemon()
            if soul_daemon:
                logger.debug(f"Soul daemon routing for self-modification: {soul_daemon}")
                return soul_daemon
            logger.warning("No soul daemon available for self-modification")
        
        # Check for "prime", "yourself", "self" targeting
        if intent.target_machine:
            target_lower = intent.target_machine.lower()
            if target_lower in ("prime", "yourself", "self", "alfred", "soul"):
                soul_daemon = self._get_soul_daemon()
                if soul_daemon:
                    logger.debug(f"Explicit soul daemon targeting: {soul_daemon}")
                    return soul_daemon
        
        # Explicit machine targeting
        if intent.target_machine:
            daemon_id = self._resolve_machine_name(intent.target_machine)
            if daemon_id:
                logger.debug(f"Explicit targeting: {intent.target_machine} -> {daemon_id}")
                return daemon_id
            logger.warning(f"Could not resolve machine: {intent.target_machine}")
        
        # Project-based routing
        project = self._detect_project(intent)
        if project and project in self.project_mappings:
            daemon_id = self.project_mappings[project]
            logger.debug(f"Project routing: {project} -> {daemon_id}")
            return daemon_id
        
        # Capability-based routing
        required_capability = self._get_required_capability(intent)
        if required_capability:
            daemon_id = self._find_capable_daemon(required_capability)
            if daemon_id:
                logger.debug(f"Capability routing: {required_capability} -> {daemon_id}")
                return daemon_id
        
        # Default to first available daemon
        return self._get_default_daemon()
    
    def _get_soul_daemon(self) -> Optional[str]:
        """Get the soul daemon (daemon running on Prime's server)."""
        for daemon_id, info in self.machine_registry.items():
            if info.get("is_soul_daemon"):
                return daemon_id
        
        # Fallback: look for daemon named "prime", "soul", or "localhost"
        for daemon_id, info in self.machine_registry.items():
            name = info.get("name", "").lower()
            if name in ("prime", "soul", "localhost", "local"):
                return daemon_id
        
        return None
    
    def get_all_capable_daemons(self, capability: str) -> List[str]:
        """Get all daemons with a specific capability."""
        return [
            daemon_id
            for daemon_id, info in self.machine_registry.items()
            if capability in info.get("capabilities", [])
            and info.get("status") == "connected"
        ]
    
    def _resolve_machine_name(self, name: str) -> Optional[str]:
        """Resolve friendly name to daemon ID."""
        name_lower = name.lower().strip()
        
        # Check aliases first
        if name_lower in self.aliases:
            return self.aliases[name_lower]
        
        # Check by daemon ID
        if name_lower in self.machine_registry:
            return name_lower
        
        # Check by name or hostname
        for daemon_id, info in self.machine_registry.items():
            if info.get("name", "").lower() == name_lower:
                return daemon_id
            if name_lower in info.get("hostname", "").lower():
                return daemon_id
            # Partial match on name
            if name_lower in info.get("name", "").lower():
                return daemon_id
        
        return None
    
    def _detect_project(self, intent: ParsedIntent) -> Optional[str]:
        """Try to detect project from intent."""
        params = intent.parameters
        command = params.get("command", "").lower()
        
        # Check for explicit project mentions
        for project_name in self.project_mappings.keys():
            if project_name.lower() in command:
                return project_name
        
        # Check for common project command patterns
        project_patterns = [
            r"in\s+(\w+)",  # "in myproject"
            r"for\s+(\w+)",  # "for myproject"
            r"(\w+)\s+project",  # "myproject project"
        ]
        
        for pattern in project_patterns:
            match = re.search(pattern, command)
            if match:
                potential_project = match.group(1)
                if potential_project in self.project_mappings:
                    return potential_project
        
        return None
    
    def _get_required_capability(self, intent: ParsedIntent) -> Optional[str]:
        """Determine required capability for this intent."""
        capability_map = {
            # Shell
            ActionType.SHELL: "shell",
            ActionType.SHELL_ROOT: "shell",
            ActionType.PYTHON: "shell",
            ActionType.NODE: "shell",
            # Files
            ActionType.READ_FILE: "files",
            ActionType.WRITE_FILE: "files",
            ActionType.DELETE_FILE: "files",
            ActionType.MOVE_FILE: "files",
            ActionType.COPY_FILE: "files",
            ActionType.LIST_FILES: "files",
            # System
            ActionType.SYSTEM_INFO: "shell",
            ActionType.PROCESS_LIST: "shell",
            ActionType.KILL_PROCESS: "shell",
            ActionType.MANAGE_SERVICE: "services",
            ActionType.INSTALL_PACKAGE: "shell",
            ActionType.NETWORK: "shell",
            # Docker
            ActionType.DOCKER: "docker",
            ActionType.DOCKER_COMPOSE: "docker",
            # Git
            ActionType.GIT: "shell",
            # Sessions
            ActionType.CREATE_SESSION: "shell",
            ActionType.LIST_SESSIONS: "shell",
            ActionType.CRON: "shell",
            # Self-mod (handled separately by soul daemon)
            ActionType.MODIFY_CODE: "soul",
            ActionType.CREATE_CODE: "soul",
            ActionType.REBUILD: "soul",
            ActionType.RESTART: "soul",
            ActionType.UPDATE_DEPS: "soul",
        }
        return capability_map.get(intent.action)
    
    def _find_capable_daemon(self, capability: str) -> Optional[str]:
        """Find a daemon with the required capability, preferring connected ones."""
        # First, try to find a connected daemon with the capability
        connected = []
        disconnected = []
        
        for daemon_id, info in self.machine_registry.items():
            if capability in info.get("capabilities", []):
                if info.get("status") == "connected":
                    connected.append((daemon_id, info.get("priority", 100)))
                else:
                    disconnected.append((daemon_id, info.get("priority", 100)))
        
        # Sort by priority (lower is better)
        if connected:
            connected.sort(key=lambda x: x[1])
            return connected[0][0]
        
        if disconnected:
            disconnected.sort(key=lambda x: x[1])
            return disconnected[0][0]
        
        return None
    
    def _get_default_daemon(self) -> Optional[str]:
        """Get the default (first connected) daemon."""
        # Prefer connected daemons
        for daemon_id, info in self.machine_registry.items():
            if info.get("status") == "connected":
                return daemon_id
        
        # Fall back to any registered daemon
        if self.machine_registry:
            return next(iter(self.machine_registry.keys()))
        
        return None
    
    def register_daemon(self, daemon_id: str, info: dict):
        """Register a daemon in the routing table."""
        self.machine_registry[daemon_id] = info
        
        # Create aliases
        name = info.get("name", "").lower()
        if name:
            self.aliases[name] = daemon_id
        
        logger.info(f"Registered daemon: {daemon_id} ({info.get('name')})")
    
    def update_daemon_status(self, daemon_id: str, status: str):
        """Update a daemon's status."""
        if daemon_id in self.machine_registry:
            self.machine_registry[daemon_id]["status"] = status
    
    def unregister_daemon(self, daemon_id: str):
        """Remove a daemon from the routing table."""
        info = self.machine_registry.pop(daemon_id, None)
        if info:
            name = info.get("name", "").lower()
            self.aliases.pop(name, None)
            logger.info(f"Unregistered daemon: {daemon_id}")
    
    def register_project(self, name: str, machine_id: str):
        """Register a project with its associated machine."""
        self.project_mappings[name] = machine_id
        logger.info(f"Registered project: {name} -> {machine_id}")
    
    def list_machines(self) -> List[dict]:
        """List all registered machines."""
        return [
            {"id": daemon_id, **info}
            for daemon_id, info in self.machine_registry.items()
        ]


# Global router instance
router = TaskRouter()
