"""Shell capability - execute commands and manage processes."""

import asyncio
import os
import signal
from datetime import datetime
from typing import Any

from alfred.common import get_logger
from alfred.common.models import TaskResult, TaskStatus
from alfred.daemon.capabilities.base import BaseCapability

logger = get_logger(__name__)


class ShellCapability(BaseCapability):
    """Execute shell commands and manage processes."""

    def __init__(self, work_dir: str = "/tmp/alfred"):
        self.work_dir = work_dir
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        os.makedirs(work_dir, exist_ok=True)

    @property
    def name(self) -> str:
        return "shell"

    @property
    def actions(self) -> list[str]:
        return ["run", "run_background", "kill", "list_processes"]

    async def execute(
        self, action: str, params: dict[str, Any], task_id: str
    ) -> TaskResult:
        """Execute a shell action."""
        started_at = datetime.utcnow()

        try:
            if action == "run":
                return await self._run_command(task_id, params, started_at)
            elif action == "run_background":
                return await self._run_background(task_id, params, started_at)
            elif action == "kill":
                return await self._kill_process(task_id, params, started_at)
            elif action == "list_processes":
                return await self._list_processes(task_id, started_at)
            else:
                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=f"Unknown action: {action}",
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                )
        except Exception as e:
            logger.exception("shell_action_failed", action=action, task_id=task_id)
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

    async def _run_command(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Run a command and wait for completion."""
        command = params.get("command")
        if not command:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'command' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        cwd = params.get("cwd", self.work_dir)
        timeout = params.get("timeout", 300)
        env = {**os.environ, **params.get("env", {})}

        logger.info("shell_run", command=command, cwd=cwd, task_id=task_id)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
                env=env,
            )

            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
                output = stdout.decode("utf-8", errors="replace")
                exit_code = process.returncode

                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.COMPLETED if exit_code == 0 else TaskStatus.FAILED,
                    output=output,
                    exit_code=exit_code,
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=f"Command timed out after {timeout}s",
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                )
        except Exception as e:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=f"Failed to execute command: {e}",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

    async def _run_background(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Run a command in the background."""
        command = params.get("command")
        if not command:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'command' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        cwd = params.get("cwd", self.work_dir)
        env = {**os.environ, **params.get("env", {})}

        logger.info("shell_run_background", command=command, task_id=task_id)

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=env,
        )

        self._processes[task_id] = process

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.RUNNING,
            output=f"Process started with PID {process.pid}",
            data={"pid": process.pid},
            started_at=started_at,
        )

    async def _kill_process(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Kill a background process."""
        target_task_id = params.get("target_task_id")
        if not target_task_id:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'target_task_id' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        process = self._processes.get(target_task_id)
        if not process:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=f"No process found for task {target_task_id}",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        sig = params.get("signal", signal.SIGTERM)
        process.send_signal(sig)

        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

        del self._processes[target_task_id]

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=f"Process {process.pid} terminated",
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

    async def _list_processes(
        self, task_id: str, started_at: datetime
    ) -> TaskResult:
        """List running background processes."""
        processes = []
        for tid, proc in list(self._processes.items()):
            if proc.returncode is None:
                processes.append({"task_id": tid, "pid": proc.pid, "running": True})
            else:
                del self._processes[tid]
                processes.append(
                    {"task_id": tid, "pid": proc.pid, "running": False, "exit_code": proc.returncode}
                )

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=f"Found {len(processes)} process(es)",
            data={"processes": processes},
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )
