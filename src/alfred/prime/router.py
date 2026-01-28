"""Task router - dispatches tasks to appropriate daemons."""

import asyncio
import uuid
from datetime import datetime
from typing import Any

import httpx

from alfred.common import get_logger
from alfred.common.models import DaemonInfo, TaskResult, TaskStatus

logger = get_logger(__name__)


class TaskRouter:
    """Routes and dispatches tasks to registered daemons."""

    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self._daemons: dict[str, DaemonInfo] = {}
        self._client = httpx.AsyncClient(timeout=300)

    def register_daemon(self, info: DaemonInfo) -> None:
        """Register a daemon."""
        self._daemons[info.name] = info
        logger.info(
            "daemon_registered",
            name=info.name,
            capabilities=[c.value for c in info.capabilities],
        )

    def unregister_daemon(self, name: str) -> None:
        """Unregister a daemon."""
        if name in self._daemons:
            del self._daemons[name]
            logger.info("daemon_unregistered", name=name)

    def get_daemon(self, name: str) -> DaemonInfo | None:
        """Get a daemon by name."""
        return self._daemons.get(name)

    def get_online_daemons(self) -> list[DaemonInfo]:
        """Get all online daemons."""
        return [d for d in self._daemons.values() if d.online]

    def get_daemons_with_capability(self, capability: str) -> list[DaemonInfo]:
        """Get daemons that have a specific capability."""
        from alfred.common.models import Capability

        try:
            cap = Capability(capability)
        except ValueError:
            return []

        return [
            d
            for d in self._daemons.values()
            if d.online and cap in d.capabilities
        ]

    def select_daemon(self, action: str, preferred: str | None = None) -> DaemonInfo | None:
        """Select the best daemon for an action."""
        # Determine required capability from action
        capability = action.split(".")[0] if "." in action else action

        candidates = self.get_daemons_with_capability(capability)
        if not candidates:
            logger.warning("no_daemon_for_capability", capability=capability)
            return None

        # If preferred daemon specified and available, use it
        if preferred:
            for d in candidates:
                if d.name == preferred:
                    return d

        # Return first available
        return candidates[0]

    async def dispatch(
        self,
        action: str,
        params: dict[str, Any],
        machine: str | None = None,
        task_id: str | None = None,
    ) -> TaskResult:
        """Dispatch a task to a daemon."""
        task_id = task_id or str(uuid.uuid4())[:8]

        daemon = self.select_daemon(action, machine)
        if not daemon:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=f"No daemon available for action: {action}",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )

        # Normalize action (shell.run -> run for the daemon)
        daemon_action = action.split(".")[-1] if "." in action else action

        url = f"http://{daemon.ip_address}:{daemon.port}/execute"

        try:
            response = await self._client.post(
                url,
                json={
                    "task_id": task_id,
                    "action": daemon_action,
                    "params": params,
                },
                headers={"Authorization": f"Bearer {self.secret_key}"},
            )

            if response.status_code == 200:
                return TaskResult(**response.json())
            else:
                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=f"Daemon returned {response.status_code}: {response.text}",
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                )

        except httpx.TimeoutException:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Request to daemon timed out",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )
        except Exception as e:
            logger.exception("dispatch_failed", daemon=daemon.name, action=action)
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )

    async def dispatch_parallel(
        self, tasks: list[dict[str, Any]]
    ) -> list[TaskResult]:
        """Dispatch multiple tasks in parallel."""

        async def dispatch_one(task: dict[str, Any]) -> TaskResult:
            return await self.dispatch(
                action=task["action"],
                params=task.get("params", {}),
                machine=task.get("machine"),
                task_id=task.get("task_id"),
            )

        results = await asyncio.gather(
            *[dispatch_one(t) for t in tasks],
            return_exceptions=True,
        )

        # Convert exceptions to failed results
        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed.append(
                    TaskResult(
                        task_id=tasks[i].get("task_id", f"task_{i}"),
                        status=TaskStatus.FAILED,
                        error=str(result),
                        started_at=datetime.utcnow(),
                        completed_at=datetime.utcnow(),
                    )
                )
            else:
                processed.append(result)

        return processed

    def update_daemon_heartbeat(self, name: str) -> bool:
        """Update daemon's last seen timestamp."""
        if name in self._daemons:
            self._daemons[name].last_seen = datetime.utcnow()
            self._daemons[name].online = True
            return True
        return False

    def mark_daemon_offline(self, name: str) -> None:
        """Mark a daemon as offline."""
        if name in self._daemons:
            self._daemons[name].online = False

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
