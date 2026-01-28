"""Alfred Brain - the central orchestrator."""

import uuid
from typing import Any

from alfred.common import get_logger
from alfred.common.models import TaskResult, TaskStatus
from alfred.memory import MemoryStore
from alfred.prime.intent import IntentParser, IntentResult
from alfred.prime.router import TaskRouter

logger = get_logger(__name__)


class AlfredBrain:
    """The central intelligence that orchestrates everything."""

    def __init__(self, router: TaskRouter, intent_parser: IntentParser):
        self.router = router
        self.intent_parser = intent_parser

    async def process_message(
        self,
        user_message: str,
        user_id: str,
        channel: str,
        memory: MemoryStore,
    ) -> str:
        """Process a user message and return a response."""

        # Get or create user and conversation
        user = await memory.get_or_create_user(user_id, channel)
        conversation = await memory.get_or_create_conversation(user, channel)

        # Store user message
        await memory.add_message(conversation, "user", user_message)

        # Get conversation history
        history = await memory.get_conversation_history(conversation)
        history_dicts = [{"role": m.role, "content": m.content} for m in history]

        # Get available machines
        machines = await memory.get_online_machines()
        machine_dicts = [
            {
                "name": m.name,
                "machine_type": m.machine_type,
                "capabilities": m.capabilities,
                "online": m.is_online,
            }
            for m in machines
        ]

        # Also include in-memory daemons from router
        for daemon in self.router.get_online_daemons():
            if not any(m["name"] == daemon.name for m in machine_dicts):
                machine_dicts.append({
                    "name": daemon.name,
                    "machine_type": daemon.machine_type,
                    "capabilities": [c.value for c in daemon.capabilities],
                    "online": daemon.online,
                })

        # Get user preferences
        preferences = await memory.get_all_preferences()

        # Parse intent
        intent_data = await self.intent_parser.parse(
            user_message=user_message,
            conversation_history=history_dicts,
            available_machines=machine_dicts,
            user_preferences=preferences,
        )

        intent = IntentResult(intent_data)

        # Handle conversational responses
        if intent.is_conversational:
            response = intent.conversational_response
            await memory.add_message(conversation, "assistant", response)
            return response

        # Handle confirmation requests
        if intent.needs_confirmation:
            response = intent.confirmation_message or "Please confirm this action."
            await memory.add_message(conversation, "assistant", response)
            return response

        # Execute tasks
        if intent.has_tasks:
            response = await self._execute_tasks(intent.tasks, memory)
        else:
            response = intent.response_preview or "I'm not sure what you'd like me to do."

        # Store assistant response
        await memory.add_message(conversation, "assistant", response)

        return response

    async def _execute_tasks(
        self, tasks: list[dict[str, Any]], memory: MemoryStore
    ) -> str:
        """Execute a list of tasks and format the response."""

        if len(tasks) == 1:
            # Single task - execute directly
            task = tasks[0]
            result = await self._execute_single_task(task, memory)
            return self._format_single_result(task, result)

        # Multiple tasks - execute in parallel
        results = await self.router.dispatch_parallel(tasks)

        # Format response
        return self._format_multiple_results(tasks, results)

    async def _execute_single_task(
        self, task: dict[str, Any], memory: MemoryStore
    ) -> TaskResult:
        """Execute a single task."""
        task_id = str(uuid.uuid4())[:8]

        # Create task record in memory
        await memory.create_task(
            task_id=task_id,
            action=task["action"],
            params=task.get("params", {}),
            machine_name=task.get("machine"),
        )

        # Dispatch to daemon
        result = await self.router.dispatch(
            action=task["action"],
            params=task.get("params", {}),
            machine=task.get("machine"),
            task_id=task_id,
        )

        # Update task record
        await memory.update_task(task_id, result)

        return result

    def _format_single_result(
        self, task: dict[str, Any], result: TaskResult
    ) -> str:
        """Format a single task result for the user."""
        description = task.get("description", task["action"])

        if result.status == TaskStatus.COMPLETED:
            if result.output:
                # Truncate long output
                output = result.output
                if len(output) > 2000:
                    output = output[:2000] + "\n... (truncated)"
                return f"{description}\n\n```\n{output}\n```"
            return f"Done: {description}"

        elif result.status == TaskStatus.RUNNING:
            return f"Started: {description}"

        else:
            error = result.error or "Unknown error"
            return f"Failed: {description}\nError: {error}"

    def _format_multiple_results(
        self, tasks: list[dict[str, Any]], results: list[TaskResult]
    ) -> str:
        """Format multiple task results for the user."""
        lines = []

        completed = sum(1 for r in results if r.status == TaskStatus.COMPLETED)
        failed = sum(1 for r in results if r.status == TaskStatus.FAILED)

        lines.append(f"Executed {len(tasks)} tasks: {completed} completed, {failed} failed")
        lines.append("")

        for task, result in zip(tasks, results):
            description = task.get("description", task["action"])
            status_icon = "+" if result.status == TaskStatus.COMPLETED else "x"
            lines.append(f"[{status_icon}] {description}")

            if result.status == TaskStatus.FAILED and result.error:
                lines.append(f"    Error: {result.error}")

        return "\n".join(lines)

    async def get_status(self) -> dict[str, Any]:
        """Get current Alfred status."""
        daemons = self.router.get_online_daemons()
        return {
            "online_daemons": len(daemons),
            "daemons": [
                {
                    "name": d.name,
                    "type": d.machine_type,
                    "capabilities": [c.value for c in d.capabilities],
                }
                for d in daemons
            ],
        }
