"""Intent parsing using Claude API."""

import logging
from typing import Optional, List, Any
from pydantic import BaseModel
from enum import Enum
import json
import re

from app.config import settings

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """Supported action types - Alfred has FULL control."""
    # Core execution
    SHELL = "shell"
    SHELL_ROOT = "shell_root"  # sudo/elevated
    PYTHON = "python"
    NODE = "node"
    
    # File operations
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    DELETE_FILE = "delete_file"
    MOVE_FILE = "move_file"
    COPY_FILE = "copy_file"
    LIST_FILES = "list_files"
    
    # System operations
    SYSTEM_INFO = "system_info"
    PROCESS_LIST = "process_list"
    KILL_PROCESS = "kill_process"
    MANAGE_SERVICE = "manage_service"
    INSTALL_PACKAGE = "install_package"
    NETWORK = "network"
    
    # Docker
    DOCKER = "docker"
    DOCKER_COMPOSE = "docker_compose"
    
    # Git
    GIT = "git"
    
    # Self-modification (Soul daemon)
    MODIFY_CODE = "modify_code"
    CREATE_CODE = "create_code"
    REBUILD = "rebuild"
    RESTART = "restart"
    UPDATE_DEPS = "update_deps"
    
    # Sessions
    CREATE_SESSION = "create_session"
    LIST_SESSIONS = "list_sessions"
    
    # Cron
    CRON = "cron"
    
    # Meta
    STATUS = "status"
    HELP = "help"
    INFO = "info"  # Questions about Alfred itself
    MACHINES = "machines"  # List connected machines
    UNKNOWN = "unknown"


class ParsedIntent(BaseModel):
    """Parsed intent from user message."""
    action: ActionType
    target_machine: Optional[str] = None
    parameters: dict = {}
    confirmation_required: bool = False
    original_message: str = ""
    confidence: float = 1.0


SYSTEM_PROMPT = """You are Alfred, a personal AI agent with FULL control over all connected machines, including the ability to modify yourself.

Parse user messages into structured intents. Output ONLY valid JSON.

## Available Actions (Full Control)

### Core Execution
| Action | Description | Parameters |
|--------|-------------|------------|
| shell | Execute any shell command | command, working_directory |
| shell_root | Execute with sudo | command, working_directory |
| python | Execute Python code | code, working_directory |
| node | Execute Node.js code | code, working_directory |

### File System (Full Access)
| Action | Description | Parameters |
|--------|-------------|------------|
| read_file | Read file | path |
| write_file | Write file | path, content |
| delete_file | Delete file/dir | path, recursive |
| move_file | Move/rename | source, destination |
| copy_file | Copy | source, destination |
| list_files | List directory | path, recursive |

### System Operations
| Action | Description | Parameters |
|--------|-------------|------------|
| system_info | Get system info | (none) |
| process_list | List processes | filter |
| kill_process | Kill process | pid, signal |
| manage_service | Manage services | service_name, action (start/stop/restart) |
| install_package | Install packages | packages |
| network | Network ops | operation, args |

### Docker & Git
| Action | Description | Parameters |
|--------|-------------|------------|
| docker | Docker command | args |
| docker_compose | Compose command | action, services |
| git | Git command | args, working_directory |

### Self-Modification (I can improve myself!)
| Action | Description | Parameters |
|--------|-------------|------------|
| modify_code | Edit my code | component (prime/daemon), file_path, old_content, new_content |
| create_code | Create new file | component, file_path, content |
| rebuild | Rebuild myself | component (prime/daemon/all) |
| restart | Restart myself | component |
| update_deps | Update deps | component |

### Sessions & Cron
| Action | Description | Parameters |
|--------|-------------|------------|
| create_session | Create tmux session | name, command |
| list_sessions | List sessions | (none) |
| cron | Manage cron | operation (list/add/remove), schedule, command |

### Meta (no daemon needed)
| Action | Description | Parameters |
|--------|-------------|------------|
| status | Check running tasks | (none) |
| help | Show help | (none) |
| info | Questions about Alfred himself | (none) |
| machines | List connected machines | (none) |

## Output Format

```json
{"action": "shell", "target_machine": null, "parameters": {"command": "ls"}, "confirmation_required": false, "confidence": 0.95}
```

## Rules

1. **Full control**: I can do ANYTHING - commands, files, services, even modify my own code.
2. **Target machine**: Use "on my macbook", "on server", "on prime/yourself" for self-modification. null = default.
3. **Self-modification**: When asked to improve/modify Alfred, use modify_code, create_code, rebuild.
4. **confirmation_required=true** for: destructive ops (rm -rf, kill), sudo, self-modification, production changes.
5. **confidence**: 0.9+ clear, 0.7-0.9 inferred, <0.7 vague.

## Examples

User: "run the tests" → {"action": "shell", "parameters": {"command": "npm test"}, "confirmation_required": false, "confidence": 0.85}

User: "restart nginx" → {"action": "manage_service", "parameters": {"service_name": "nginx", "action": "restart"}, "confirmation_required": true, "confidence": 0.95}

User: "docker ps" → {"action": "docker", "parameters": {"args": ["ps"]}, "confirmation_required": false, "confidence": 0.98}

User: "kill process 12345" → {"action": "kill_process", "parameters": {"pid": 12345, "signal": 15}, "confirmation_required": true, "confidence": 0.95}

User: "git pull on server" → {"action": "git", "target_machine": "server", "parameters": {"args": ["pull"]}, "confirmation_required": false, "confidence": 0.95}

User: "improve yourself to be faster" → {"action": "modify_code", "target_machine": "prime", "parameters": {"component": "prime", "description": "optimization"}, "confirmation_required": true, "confidence": 0.7}

User: "update your dependencies" → {"action": "update_deps", "parameters": {"component": "all"}, "confirmation_required": true, "confidence": 0.9}
"""


# Quick pattern matching for common commands (fallback if API unavailable)
QUICK_PATTERNS = [
    # Meta - questions about Alfred itself (no daemon needed)
    (r"^(help|hi|hello|hey)\b", ActionType.HELP, {}),
    (r"^status\b", ActionType.STATUS, {}),
    (r"^(what'?s running|running tasks)\b", ActionType.STATUS, {}),
    (r"^(machines?|daemons?|list machines?|connected)\b", ActionType.MACHINES, {}),
    (r"^(who are you|what are you|about)\b", ActionType.INFO, {}),
    (r"^(which machine|where are you|what machine)\b", ActionType.INFO, {}),
    
    # Shell
    (r"^ls\s*(.*)", ActionType.SHELL, lambda m: {"command": f"ls {m.group(1)}".strip()}),
    (r"^cat\s+(.+)", ActionType.READ_FILE, lambda m: {"path": m.group(1).strip()}),
    (r"^(run|exec|execute)\s+(.+)", ActionType.SHELL, lambda m: {"command": m.group(2).strip()}),
    (r"^pwd\b", ActionType.SHELL, {"command": "pwd"}),
    (r"^whoami\b", ActionType.SHELL, {"command": "whoami"}),
    (r"^df\b", ActionType.SHELL, {"command": "df -h"}),
    (r"^ps\b", ActionType.PROCESS_LIST, {}),
    (r"^top\b", ActionType.SHELL, {"command": "top -l 1 -n 10"}),
    
    # Docker
    (r"^docker\s+(.+)", ActionType.DOCKER, lambda m: {"args": m.group(1).split()}),
    (r"^docker-compose\s+(.+)", ActionType.DOCKER_COMPOSE, lambda m: {"action": m.group(1).split()[0]}),
    
    # Git
    (r"^git\s+(.+)", ActionType.GIT, lambda m: {"args": m.group(1).split()}),
    
    # System
    (r"^(restart|start|stop)\s+(service\s+)?(\w+)", ActionType.MANAGE_SERVICE, 
     lambda m: {"action": m.group(1), "service_name": m.group(3)}),
    (r"^kill\s+(\d+)", ActionType.KILL_PROCESS, lambda m: {"pid": int(m.group(1)), "signal": 15}),
    (r"^(install|apt install|brew install)\s+(.+)", ActionType.INSTALL_PACKAGE, 
     lambda m: {"packages": m.group(2).split()}),
    
    # Sessions
    (r"^(tmux|sessions?)\b", ActionType.LIST_SESSIONS, {}),
    
    # System info
    (r"^(sysinfo|system info|machine info)\b", ActionType.SYSTEM_INFO, {}),
]


def quick_parse(message: str) -> Optional[ParsedIntent]:
    """Quick pattern-based parsing for common commands."""
    message_lower = message.lower().strip()
    
    for pattern, action, param_fn in QUICK_PATTERNS:
        match = re.match(pattern, message_lower, re.IGNORECASE)
        if match:
            params = param_fn(match) if callable(param_fn) else param_fn
            return ParsedIntent(
                action=action,
                parameters=params,
                original_message=message,
                confidence=0.95,
                confirmation_required=False,
            )
    
    return None


async def parse_intent(message: str) -> ParsedIntent:
    """Parse user message into structured intent using Claude."""
    
    # Try learned patterns first
    try:
        from app.core.patterns import pattern_learner
        
        pattern = pattern_learner.match(message)
        if pattern:
            logger.debug(f"Learned pattern matched: {pattern.trigger}")
            pattern_learner.use_pattern(pattern.id)
            
            action_map = {
                # Core
                "shell": ActionType.SHELL,
                "shell_root": ActionType.SHELL_ROOT,
                "python": ActionType.PYTHON,
                "node": ActionType.NODE,
                # Files
                "read_file": ActionType.READ_FILE,
                "write_file": ActionType.WRITE_FILE,
                "delete_file": ActionType.DELETE_FILE,
                "move_file": ActionType.MOVE_FILE,
                "copy_file": ActionType.COPY_FILE,
                "list_files": ActionType.LIST_FILES,
                # System
                "system_info": ActionType.SYSTEM_INFO,
                "process_list": ActionType.PROCESS_LIST,
                "kill_process": ActionType.KILL_PROCESS,
                "manage_service": ActionType.MANAGE_SERVICE,
                "install_package": ActionType.INSTALL_PACKAGE,
                "network": ActionType.NETWORK,
                # Docker/Git
                "docker": ActionType.DOCKER,
                "docker_compose": ActionType.DOCKER_COMPOSE,
                "git": ActionType.GIT,
                # Self-mod
                "modify_code": ActionType.MODIFY_CODE,
                "create_code": ActionType.CREATE_CODE,
                "rebuild": ActionType.REBUILD,
                "restart": ActionType.RESTART,
                "update_deps": ActionType.UPDATE_DEPS,
                # Sessions
                "create_session": ActionType.CREATE_SESSION,
                "list_sessions": ActionType.LIST_SESSIONS,
                "cron": ActionType.CRON,
                # Meta
                "status": ActionType.STATUS,
                "help": ActionType.HELP,
                "info": ActionType.INFO,
                "machines": ActionType.MACHINES,
            }
            
            return ParsedIntent(
                action=action_map.get(pattern.action, ActionType.SHELL),
                target_machine=pattern.target_machine,
                parameters=pattern.parameters,
                original_message=message,
                confidence=0.95,
                confirmation_required=_is_dangerous_command(
                    pattern.parameters.get("command", "")
                ),
            )
    except Exception as e:
        logger.debug(f"Pattern matching failed: {e}")
    
    # Try quick pattern matching next
    quick_result = quick_parse(message)
    if quick_result:
        logger.debug(f"Quick parse matched: {quick_result.action}")
        return quick_result
    
    # Check if Claude API is configured
    if not settings.claude_api_key:
        logger.warning("Claude API key not configured, using basic parsing")
        # Fall back to treating as shell command
        return ParsedIntent(
            action=ActionType.SHELL,
            parameters={"command": message},
            original_message=message,
            confidence=0.6,
            confirmation_required=_is_dangerous_command(message),
        )
    
    try:
        import anthropic
        
        client = anthropic.Anthropic(api_key=settings.claude_api_key)
        
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": message}
            ],
        )
        
        # Extract JSON from response
        content = response.content[0].text.strip()
        logger.debug(f"Claude response: {content}")
        
        # Parse JSON
        data = _extract_json(content)
        
        # Validate action
        action_str = data.get("action", "unknown")
        try:
            action = ActionType(action_str)
        except ValueError:
            action = ActionType.UNKNOWN
        
        return ParsedIntent(
            action=action,
            target_machine=data.get("target_machine"),
            parameters=data.get("parameters", {}),
            confirmation_required=data.get("confirmation_required", False),
            original_message=message,
            confidence=float(data.get("confidence", 0.8)),
        )
        
    except Exception as e:
        logger.error(f"Intent parsing error: {e}")
        # Fallback: treat as shell command
        return ParsedIntent(
            action=ActionType.SHELL,
            parameters={"command": message},
            original_message=message,
            confidence=0.5,
            confirmation_required=_is_dangerous_command(message),
        )


def _extract_json(content: str) -> dict:
    """Extract JSON from Claude's response, handling markdown blocks."""
    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    # Try to extract from markdown code block
    patterns = [
        r"```json\s*(.*?)\s*```",
        r"```\s*(.*?)\s*```",
        r"\{.*\}",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1) if match.lastindex else match.group(0))
            except (json.JSONDecodeError, IndexError):
                continue
    
    raise ValueError(f"Could not extract JSON from: {content[:200]}")


def _is_dangerous_command(command: str) -> bool:
    """Check if a command is potentially dangerous."""
    dangerous_patterns = [
        r"\brm\s+(-rf?|--recursive)",
        r"\brm\s+",
        r"\bdrop\s+(database|table)",
        r"\bdelete\s+",
        r"\btruncate\s+",
        r"\bkill\s+",
        r"\bsudo\s+",
        r"\bdeploy\s+.*prod",
        r"\bpush\s+.*prod",
        r"\bgit\s+push\s+.*-f",
        r"\bgit\s+reset\s+--hard",
    ]
    
    command_lower = command.lower()
    for pattern in dangerous_patterns:
        if re.search(pattern, command_lower):
            return True
    
    return False


async def format_response(intent: ParsedIntent, result: Any) -> str:
    """Format execution result for user-friendly response."""
    
    if intent.action == ActionType.SHELL:
        if isinstance(result, dict):
            if result.get("success"):
                output = result.get("output", "").strip()
                if not output:
                    return "✓ Done."
                
                # Truncate long output
                if len(output) > 2000:
                    output = output[:2000] + "\n\n... (output truncated)"
                
                return f"```\n{output}\n```"
            else:
                error = result.get("error", "Unknown error")
                return f"❌ **Error:** {error}"
        return str(result)
    
    elif intent.action == ActionType.READ_FILE:
        if isinstance(result, dict):
            if result.get("success"):
                content = result.get("content", "")
                if len(content) > 2000:
                    content = content[:2000] + "\n\n... (file truncated)"
                return f"```\n{content}\n```"
            else:
                return f"❌ **Error reading file:** {result.get('error', 'Unknown error')}"
        return str(result)
    
    elif intent.action == ActionType.LIST_FILES:
        if isinstance(result, dict):
            files = result.get("files", [])
            if not files:
                return "Directory is empty."
            
            output = "\n".join([
                f"{'📁' if f.get('is_directory') else '📄'} {f.get('name', 'unknown')}"
                for f in files[:50]
            ])
            
            if len(files) > 50:
                output += f"\n\n... and {len(files) - 50} more files"
            
            return output
        return str(result)
    
    elif intent.action == ActionType.STATUS:
        if isinstance(result, dict):
            count = result.get("running_count", 0)
            if count == 0:
                return "No tasks currently running."
            
            tasks = result.get("tasks", [])
            lines = [f"**{count} task(s) running:**\n"]
            for t in tasks:
                lines.append(f"• `{t.get('action')}` on {t.get('daemon')} ({t.get('running_for')})")
            
            return "\n".join(lines)
        return str(result)
    
    elif intent.action == ActionType.HELP:
        return """👋 **I'm Alfred, your personal AI agent with FULL control.**

**I can do ANYTHING on your machines:**

**Execute Commands**
• "run the tests" / "npm install" / any shell command
• "restart nginx" - Service management
• "install htop" - Package management
• "docker ps" / "docker-compose up" - Container management

**Files & System**
• "show me /etc/hosts" / "delete old logs"
• "df -h" / "ps aux" / "kill process 1234"
• "git pull" / "git commit" - Full git access

**Multi-Machine**
• "on my macbook, run..." / "on server, restart nginx"
• I route commands automatically based on context

**Self-Improvement**
• "update your dependencies"
• "improve yourself to handle X"
• I can modify my own code!

**Sessions & Automation**
• "create a session for the build"
• "add cron job for daily backup"

Just tell me what you need. I have full control."""
    
    elif intent.action == ActionType.UNKNOWN:
        return f"I couldn't understand that. Try rephrasing or type 'help'."
    
    return str(result) if result else "Done."
