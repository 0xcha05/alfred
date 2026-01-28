"""Intent parser - understands user intent using Claude."""

from typing import Any

import anthropic

from alfred.common import get_logger
from alfred.config import get_settings

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are Alfred, a persistent AI assistant that manages tasks across multiple machines.

You understand user intent and convert it into actionable tasks. You have access to:
- Multiple machines (daemons) that can execute shell commands and file operations
- Memory of the user's projects, preferences, and past interactions

When a user gives you a request:
1. Understand what they want to accomplish
2. Determine which machine(s) should handle it
3. Break it into concrete actions

You respond with JSON describing the tasks to execute.

Available actions:
- shell.run: Execute a shell command (params: command, cwd, timeout, env)
- shell.run_background: Run command in background (params: command, cwd, env)
- shell.kill: Kill a background process (params: target_task_id)
- files.read: Read a file (params: path)
- files.write: Write to a file (params: path, content)
- files.list: List directory contents (params: path)
- files.delete: Delete file/directory (params: path, recursive)
- files.move: Move file/directory (params: source, destination)
- files.copy: Copy file/directory (params: source, destination)

Response format:
{
    "understanding": "Brief description of what the user wants",
    "tasks": [
        {
            "action": "shell.run",
            "params": {"command": "..."},
            "machine": "machine_name or null for auto",
            "description": "What this task does"
        }
    ],
    "needs_confirmation": false,
    "confirmation_message": null,
    "response_preview": "What you'll say when done"
}

If the request is conversational (greeting, question about yourself, etc.), respond with:
{
    "understanding": "...",
    "tasks": [],
    "conversational_response": "Your response to the user"
}

Always be concise. The user speaks intent, not instructions."""


class IntentParser:
    """Parses user intent using Claude."""

    def __init__(self):
        settings = get_settings()
        self.client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self.model = "claude-sonnet-4-20250514"

    async def parse(
        self,
        user_message: str,
        conversation_history: list[dict[str, str]],
        available_machines: list[dict[str, Any]],
        user_preferences: dict[str, Any],
    ) -> dict[str, Any]:
        """Parse user intent and return structured task plan."""

        context = self._build_context(available_machines, user_preferences)

        messages = []
        for msg in conversation_history[-10:]:  # Last 10 messages for context
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT + "\n\n" + context,
                messages=messages,
            )

            response_text = response.content[0].text

            # Parse JSON from response
            import json

            # Try to extract JSON from the response
            try:
                # First try direct parse
                result = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to find JSON in the response
                import re

                json_match = re.search(r"\{[\s\S]*\}", response_text)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    # Fallback to conversational response
                    result = {
                        "understanding": "conversational",
                        "tasks": [],
                        "conversational_response": response_text,
                    }

            logger.info(
                "intent_parsed",
                understanding=result.get("understanding"),
                task_count=len(result.get("tasks", [])),
            )

            return result

        except Exception as e:
            logger.exception("intent_parsing_failed")
            return {
                "understanding": "error",
                "tasks": [],
                "conversational_response": f"I encountered an error understanding your request: {e}",
            }

    def _build_context(
        self, machines: list[dict[str, Any]], preferences: dict[str, Any]
    ) -> str:
        """Build context string for the model."""
        parts = []

        if machines:
            machine_list = "\n".join(
                f"- {m['name']} ({m['machine_type']}): capabilities={m['capabilities']}, online={m['online']}"
                for m in machines
            )
            parts.append(f"Available machines:\n{machine_list}")
        else:
            parts.append("No machines currently registered.")

        if preferences:
            pref_list = "\n".join(f"- {k}: {v}" for k, v in preferences.items())
            parts.append(f"User preferences:\n{pref_list}")

        return "\n\n".join(parts)


class IntentResult:
    """Structured result from intent parsing."""

    def __init__(self, data: dict[str, Any]):
        self.understanding = data.get("understanding", "")
        self.tasks = data.get("tasks", [])
        self.needs_confirmation = data.get("needs_confirmation", False)
        self.confirmation_message = data.get("confirmation_message")
        self.response_preview = data.get("response_preview")
        self.conversational_response = data.get("conversational_response")

    @property
    def is_conversational(self) -> bool:
        """Check if this is a conversational response (no tasks)."""
        return len(self.tasks) == 0 and self.conversational_response is not None

    @property
    def has_tasks(self) -> bool:
        """Check if there are tasks to execute."""
        return len(self.tasks) > 0
