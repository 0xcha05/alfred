"""Base capability interface."""

from abc import ABC, abstractmethod
from typing import Any

from alfred.common.models import TaskResult


class BaseCapability(ABC):
    """Abstract base class for daemon capabilities."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this capability."""
        pass

    @property
    @abstractmethod
    def actions(self) -> list[str]:
        """List of actions this capability supports."""
        pass

    @abstractmethod
    async def execute(
        self, action: str, params: dict[str, Any], task_id: str
    ) -> TaskResult:
        """Execute an action with the given parameters."""
        pass

    def supports_action(self, action: str) -> bool:
        """Check if this capability supports the given action."""
        return action in self.actions
