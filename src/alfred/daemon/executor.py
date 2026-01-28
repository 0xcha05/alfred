"""Task executor - routes tasks to capabilities."""

from datetime import datetime
from typing import Any

from alfred.common import get_logger
from alfred.common.models import TaskResult, TaskStatus
from alfred.daemon.capabilities.base import BaseCapability

logger = get_logger(__name__)


class TaskExecutor:
    """Routes tasks to appropriate capabilities and executes them."""

    def __init__(self):
        self._capabilities: dict[str, BaseCapability] = {}
        self._action_map: dict[str, BaseCapability] = {}

    def register_capability(self, capability: BaseCapability) -> None:
        """Register a capability."""
        self._capabilities[capability.name] = capability
        for action in capability.actions:
            if action in self._action_map:
                logger.warning(
                    "action_override",
                    action=action,
                    old=self._action_map[action].name,
                    new=capability.name,
                )
            self._action_map[action] = capability
        logger.info(
            "capability_registered",
            name=capability.name,
            actions=capability.actions,
        )

    def get_capabilities(self) -> list[str]:
        """Get list of registered capability names."""
        return list(self._capabilities.keys())

    def get_actions(self) -> list[str]:
        """Get list of all available actions."""
        return list(self._action_map.keys())

    async def execute(
        self, task_id: str, action: str, params: dict[str, Any]
    ) -> TaskResult:
        """Execute a task."""
        capability = self._action_map.get(action)

        if not capability:
            logger.warning("unknown_action", action=action, task_id=task_id)
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=f"Unknown action: {action}. Available: {', '.join(self._action_map.keys())}",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )

        logger.info(
            "executing_task",
            task_id=task_id,
            action=action,
            capability=capability.name,
        )

        result = await capability.execute(action, params, task_id)

        logger.info(
            "task_completed",
            task_id=task_id,
            status=result.status.value,
            has_error=result.error is not None,
        )

        return result
