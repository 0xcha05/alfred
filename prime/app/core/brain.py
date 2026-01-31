"""Alfred's Brain - Claude-powered thinking and decision making.

This is the core intelligence. Every message goes through here.
Claude decides what to do - respond, execute, or both.
"""

import asyncio
import logging
import json
import subprocess
import os
from typing import Optional
from anthropic import AsyncAnthropic

from app.config import settings
from app.grpc_server import daemon_registry, execute_shell, read_file, write_file, list_files

logger = logging.getLogger(__name__)

# Initialize Claude
client = AsyncAnthropic(api_key=settings.claude_api_key)

# Prime server info
PRIME_HOSTNAME = os.uname().nodename


def get_system_context(history_file: Optional[str] = None, total_messages: int = 0) -> str:
    """Build the system prompt with current state."""
    
    # Get connected machines
    daemons = daemon_registry.list_all()
    
    machines_list = [f"  - prime (this server, {PRIME_HOSTNAME}): Always available"]
    
    if daemons:
        for d in daemons:
            machines_list.append(
                f"  - {d.name} ({d.hostname}): {d.status}, CPU: {d.cpu_percent:.1f}%, Mem: {d.memory_percent:.1f}%"
            )
    
    machines_section = f"""AVAILABLE MACHINES:
{chr(10).join(machines_list)}

You can execute commands on any of these machines. Use "prime" for this server."""
    
    return f"""You are Ultron, an AI assistant with full control over connected machines.

{machines_section}

CAPABILITIES:
- Execute shell commands on any connected machine
- Read, write, delete files
- Browse the web, search for information
- Schedule tasks (recurring or one-time)
- Docker, Git, services, processes
- Receive files from user (auto-downloaded to /home/ec2-user/alfred/data/media/)
- Send files back to user via Telegram (video, photo, audio, documents)

BEHAVIOR:
- Be concise and direct
- Execute first, report results
- Don't over-explain or narrate your process
- If something fails, briefly explain and move on

MULTI-STEP TASKS:
- For complex file processing: use create_workspace first, then workspace_add_source to copy files in
- Workspaces have: input/ (sources), steps/ (intermediates), output/ (final)
- Combine operations into a single command when possible
- If multiple steps are needed, output to steps/step1_xxx, steps/step2_xxx, etc.
- Final result goes to output/, then send_file from there
- Never overwrite source files - always output to new paths

CONTEXT:
- Messages in conversation: {total_messages}
- History file: {history_file if history_file else "Not yet created"}"""


async def think(
    message: str,
    chat_id: int,
    conversation_history: Optional[list] = None,
    history_file: Optional[str] = None,
    total_messages: int = 0,
) -> dict:
    """
    Process a message through Claude and decide what to do.
    
    Returns:
        {
            "response": str,  # Text response to send back
            "executed": bool,  # Whether a command was executed
            "result": dict,  # Execution result if any
        }
    """
    
    # Build tools for Claude - always available since prime is always available
    daemons = daemon_registry.list_all()
    daemon_names = ["prime"] + [d.name for d in daemons]
    
    tools = [
        {
            "name": "execute_shell",
            "description": f"Execute a shell command on a machine. Available: {', '.join(daemon_names)}. Use 'prime' for this server.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute"
                    },
                    "machine": {
                        "type": "string",
                        "description": f"Which machine to run on. Options: {', '.join(daemon_names)}. Default: prime",
                    },
                    "as_root": {
                        "type": "boolean",
                        "description": "Whether to run with sudo",
                    }
                },
                "required": ["command"]
            }
        },
        {
            "name": "read_file",
            "description": f"Read a file from a machine. Available: {', '.join(daemon_names)}",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file"
                    },
                    "machine": {
                        "type": "string",
                        "description": f"Which machine. Options: {', '.join(daemon_names)}. Default: prime",
                    }
                },
                "required": ["path"]
            }
        },
        {
            "name": "write_file",
            "description": f"Write content to a file. Available: {', '.join(daemon_names)}",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write"
                    },
                    "machine": {
                        "type": "string",
                        "description": f"Which machine. Options: {', '.join(daemon_names)}. Default: prime",
                    }
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "list_files",
            "description": f"List files in a directory. Available: {', '.join(daemon_names)}",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path"
                    },
                    "machine": {
                        "type": "string",
                        "description": f"Which machine. Options: {', '.join(daemon_names)}. Default: prime",
                    }
                },
                "required": ["path"]
            }
        },
        # Scheduling tools
        {
            "name": "schedule_task",
            "description": "Schedule a recurring or one-time task. Use this when user asks for reminders, periodic updates, or scheduled actions.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short name for the task"
                    },
                    "action": {
                        "type": "string",
                        "description": "What to do when the task runs (natural language instruction)"
                    },
                    "interval_minutes": {
                        "type": "integer",
                        "description": "Run every N minutes. Use this for recurring tasks."
                    },
                    "run_once_in_minutes": {
                        "type": "integer",
                        "description": "Run once after N minutes. Use this for one-time reminders."
                    }
                },
                "required": ["name", "action"]
            }
        },
        {
            "name": "list_scheduled_tasks",
            "description": "List all scheduled tasks",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "cancel_scheduled_task",
            "description": "Cancel a scheduled task by ID",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task ID to cancel"
                    }
                },
                "required": ["task_id"]
            }
        },
        # Web/HTTP tools
        {
            "name": "web_search",
            "description": "Search the web for information. Returns search results.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "fetch_url",
            "description": "Fetch content from a URL. Use for reading web pages, APIs, etc.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch"
                    },
                    "method": {
                        "type": "string",
                        "description": "HTTP method (GET, POST, etc.). Default: GET"
                    },
                    "headers": {
                        "type": "object",
                        "description": "Optional HTTP headers"
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional request body for POST/PUT"
                    }
                },
                "required": ["url"]
            }
        },
        {
            "name": "send_message",
            "description": "Send a message to a specific destination. Use for proactive messaging.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "destination": {
                        "type": "string",
                        "description": "Where to send: 'telegram', 'webhook:URL', etc."
                    },
                    "message": {
                        "type": "string",
                        "description": "The message to send"
                    },
                    "chat_id": {
                        "type": "integer",
                        "description": "For telegram: the chat ID"
                    }
                },
                "required": ["destination", "message"]
            }
        },
        {
            "name": "send_file",
            "description": "Send a file via Telegram. Automatically detects type (video/photo/audio/document). Use for sending processed files back to user.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the file to send"
                    },
                    "caption": {
                        "type": "string",
                        "description": "Optional caption for the file"
                    },
                    "chat_id": {
                        "type": "integer",
                        "description": "The chat ID to send to"
                    }
                },
                "required": ["file_path", "chat_id"]
            }
        },
        # Workspace tools for multi-step tasks
        {
            "name": "create_workspace",
            "description": "Create an isolated workspace for a multi-step task. Use this when processing files with multiple operations (video editing, image processing, etc). The workspace has: input/ (source files), steps/ (intermediate results), output/ (final files). This prevents steps from overwriting each other.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_name": {
                        "type": "string",
                        "description": "Short name for the task (e.g., 'video_edit', 'image_resize')"
                    }
                },
                "required": ["task_name"]
            }
        },
        {
            "name": "workspace_add_source",
            "description": "Copy a source file into a workspace's input directory. Always use this before processing - never modify files in place.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": "The workspace ID"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to the source file to copy in"
                    }
                },
                "required": ["workspace_id", "file_path"]
            }
        },
        {
            "name": "workspace_get_path",
            "description": "Get the path to a workspace directory for running commands. Returns paths to input/, steps/, and output/ directories.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": "The workspace ID"
                    }
                },
                "required": ["workspace_id"]
            }
        }
    ]
    
    # Build messages
    messages = []
    
    # Add conversation history if available
    # Filter to only valid roles and non-empty content
    if conversation_history:
        for msg in conversation_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Skip empty messages
            if not content or not content.strip():
                continue
            
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": content})
            else:
                # Convert other roles to user (e.g., "system" messages)
                messages.append({"role": "user", "content": content})
    
    # Add current message (skip if empty)
    if message and message.strip():
        messages.append({"role": "user", "content": message})
    
    try:
        # Build system context with history info
        system_context = get_system_context(history_file, total_messages)
        
        # Call Claude
        response = await client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=2048,
            system=system_context,
            tools=tools,
            messages=messages,
        )
        
        # Process response
        result = {
            "response": "",
            "executed": False,
            "results": [],
        }
        
        # Handle tool use
        while response.stop_reason == "tool_use":
            # Find tool use blocks
            tool_results = []
            
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id
                    
                    logger.info(f"Executing tool: {tool_name} with {tool_input}")
                    
                    # Execute the tool
                    try:
                        # Add context for scheduling tools
                        if tool_name == "schedule_task":
                            tool_input["_context"] = {"chat_id": chat_id}
                        
                        tool_result = await execute_tool(tool_name, tool_input, daemons)
                        result["executed"] = True
                        result["results"].append({
                            "tool": tool_name,
                            "input": tool_input,
                            "output": tool_result
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result)
                        })
                    except Exception as e:
                        logger.error(f"Tool execution failed: {e}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": f"Error: {str(e)}",
                            "is_error": True
                        })
            
            # Continue conversation with tool results
            # Convert response.content to serializable format
            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
            
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})
            
            response = await client.messages.create(
                model="claude-opus-4-5-20251101",
                max_tokens=2048,
                system=system_context,
                tools=tools,
                messages=messages,
            )
        
        # Extract text response
        for block in response.content:
            if hasattr(block, "text"):
                result["response"] = block.text
                break
        
        return result
        
    except Exception as e:
        logger.error(f"Brain error: {e}")
        return {
            "response": f"Something went wrong in my brain: {e}",
            "executed": False,
            "results": [],
        }


async def execute_tool(tool_name: str, tool_input: dict, daemons: list) -> dict:
    """Execute a tool and return the result."""
    
    # Get target machine, default to prime
    machine = tool_input.get("machine", "prime")
    
    # Check if running on prime (local execution)
    is_local = machine.lower() in ("prime", "local", "this", "self", PRIME_HOSTNAME.lower())
    
    if tool_name == "execute_shell":
        command = tool_input.get("command")
        as_root = tool_input.get("as_root", False)
        
        if as_root:
            command = f"sudo {command}"
        
        if is_local:
            return await execute_local_shell(command)
        else:
            return await execute_shell(machine, command)
    
    elif tool_name == "read_file":
        path = tool_input.get("path")
        
        if is_local:
            return await read_local_file(path)
        else:
            return await read_file(machine, path)
    
    elif tool_name == "write_file":
        path = tool_input.get("path")
        content = tool_input.get("content")
        
        if is_local:
            return await write_local_file(path, content)
        else:
            return await write_file(machine, path, content)
    
    elif tool_name == "list_files":
        path = tool_input.get("path")
        
        if is_local:
            return await list_local_files(path)
        else:
            return await list_files(machine, path)
    
    elif tool_name == "schedule_task":
        from app.services.scheduler import scheduler
        
        name = tool_input.get("name", "Unnamed task")
        action = tool_input.get("action", "")
        interval = tool_input.get("interval_minutes")
        run_once = tool_input.get("run_once_in_minutes")
        
        # Get context from the current execution (will be passed in)
        context = tool_input.get("_context", {})
        
        task_id = await scheduler.add_task(
            name=name,
            description=action,
            interval_minutes=interval if interval else run_once,
            action=action,
            context=context,
        )
        
        # Disable after first run if one-time
        if run_once and not interval:
            task = await scheduler.get_task(task_id)
            if task:
                task.interval_minutes = None  # Will disable after first run
        
        return {
            "success": True,
            "task_id": task_id,
            "message": f"Scheduled task '{name}' (ID: {task_id})",
            "interval": interval or run_once,
            "recurring": bool(interval),
        }
    
    elif tool_name == "list_scheduled_tasks":
        from app.services.scheduler import scheduler
        
        tasks = await scheduler.list_tasks()
        if not tasks:
            return {"tasks": [], "message": "No scheduled tasks"}
        
        task_list = []
        for t in tasks:
            task_list.append({
                "id": t.id,
                "name": t.name,
                "action": t.action,
                "interval_minutes": t.interval_minutes,
                "next_run": t.next_run,
                "enabled": t.enabled,
                "run_count": t.run_count,
            })
        
        return {"tasks": task_list, "count": len(task_list)}
    
    elif tool_name == "cancel_scheduled_task":
        from app.services.scheduler import scheduler
        
        task_id = tool_input.get("task_id")
        if not task_id:
            return {"error": "No task_id provided"}
        
        success = await scheduler.remove_task(task_id)
        if success:
            return {"success": True, "message": f"Cancelled task {task_id}"}
        else:
            return {"success": False, "error": f"Task {task_id} not found"}
    
    elif tool_name == "web_search":
        return await web_search(tool_input.get("query", ""))
    
    elif tool_name == "fetch_url":
        return await fetch_url(
            url=tool_input.get("url"),
            method=tool_input.get("method", "GET"),
            headers=tool_input.get("headers"),
            body=tool_input.get("body"),
        )
    
    elif tool_name == "send_message":
        return await send_message_action(
            destination=tool_input.get("destination"),
            message=tool_input.get("message"),
            chat_id=tool_input.get("chat_id"),
        )
    
    elif tool_name == "send_file":
        return await send_file_action(
            file_path=tool_input.get("file_path"),
            chat_id=tool_input.get("chat_id"),
            caption=tool_input.get("caption"),
        )
    
    elif tool_name == "create_workspace":
        return create_workspace_action(
            task_name=tool_input.get("task_name", "task"),
        )
    
    elif tool_name == "workspace_add_source":
        return workspace_add_source_action(
            workspace_id=tool_input.get("workspace_id"),
            file_path=tool_input.get("file_path"),
        )
    
    elif tool_name == "workspace_get_path":
        return workspace_get_path_action(
            workspace_id=tool_input.get("workspace_id"),
        )
    
    else:
        return {"error": f"Unknown tool: {tool_name}"}


async def execute_local_shell(command: str) -> dict:
    """Execute a shell command locally on the Prime server."""
    try:
        # Run in executor to not block
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        )
        
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out after 60 seconds", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


async def read_local_file(path: str) -> dict:
    """Read a file locally on the Prime server."""
    try:
        with open(path, "r") as f:
            content = f.read()
        return {"content": content, "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


async def write_local_file(path: str, content: str) -> dict:
    """Write a file locally on the Prime server."""
    try:
        with open(path, "w") as f:
            f.write(content)
        return {"success": True, "message": f"Wrote {len(content)} bytes to {path}"}
    except Exception as e:
        return {"error": str(e), "success": False}


async def list_local_files(path: str) -> dict:
    """List files in a directory locally on the Prime server."""
    try:
        entries = os.listdir(path)
        files = []
        for entry in entries:
            full_path = os.path.join(path, entry)
            files.append({
                "name": entry,
                "is_dir": os.path.isdir(full_path),
                "size": os.path.getsize(full_path) if os.path.isfile(full_path) else 0,
            })
        return {"files": files, "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


async def web_search(query: str) -> dict:
    """Search the web using DuckDuckGo (no API key needed)."""
    import httpx
    
    if not query:
        return {"error": "No query provided"}
    
    try:
        # Use DuckDuckGo HTML search (simple, no API key)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Alfred/1.0"},
            )
            
            # Parse results (basic extraction)
            html = response.text
            results = []
            
            # Simple regex to extract result titles and snippets
            import re
            
            # Find result blocks
            result_blocks = re.findall(
                r'class="result__title".*?href="([^"]*)"[^>]*>([^<]*)</a>.*?'
                r'class="result__snippet"[^>]*>([^<]*)',
                html, re.DOTALL
            )
            
            for url, title, snippet in result_blocks[:5]:
                results.append({
                    "title": title.strip(),
                    "url": url,
                    "snippet": snippet.strip()[:200],
                })
            
            if not results:
                # Fallback: just return that we searched
                return {
                    "query": query,
                    "message": "Search completed but no structured results extracted. Try fetch_url with a specific site.",
                    "success": True
                }
            
            return {"query": query, "results": results, "success": True}
            
    except Exception as e:
        return {"error": f"Search failed: {e}", "success": False}


async def fetch_url(url: str, method: str = "GET", headers: dict = None, body: str = None) -> dict:
    """Fetch content from a URL."""
    import httpx
    
    if not url:
        return {"error": "No URL provided"}
    
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            request_headers = {"User-Agent": "Alfred/1.0"}
            if headers:
                request_headers.update(headers)
            
            if method.upper() == "GET":
                response = await client.get(url, headers=request_headers)
            elif method.upper() == "POST":
                response = await client.post(url, headers=request_headers, content=body)
            elif method.upper() == "PUT":
                response = await client.put(url, headers=request_headers, content=body)
            elif method.upper() == "DELETE":
                response = await client.delete(url, headers=request_headers)
            else:
                return {"error": f"Unsupported method: {method}"}
            
            # Limit response size
            content = response.text[:10000]
            
            return {
                "url": url,
                "status_code": response.status_code,
                "content": content,
                "content_type": response.headers.get("content-type", ""),
                "success": response.is_success,
            }
            
    except Exception as e:
        return {"error": f"Fetch failed: {e}", "success": False}


async def send_message_action(destination: str, message: str, chat_id: int = None) -> dict:
    """Send a message to a destination."""
    import httpx
    
    if not destination or not message:
        return {"error": "destination and message required"}
    
    try:
        if destination == "telegram":
            if not chat_id:
                return {"error": "chat_id required for telegram"}
            
            from app.services.telegram_service import telegram_service
            await telegram_service.send_message(chat_id=chat_id, text=message)
            return {"success": True, "destination": "telegram", "chat_id": chat_id}
        
        elif destination.startswith("webhook:"):
            webhook_url = destination[8:]  # Remove "webhook:" prefix
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    webhook_url,
                    json={"message": message},
                )
                return {
                    "success": response.is_success,
                    "destination": webhook_url,
                    "status_code": response.status_code,
                }
        
        else:
            return {"error": f"Unknown destination: {destination}"}
            
    except Exception as e:
        return {"error": f"Send failed: {e}", "success": False}


async def send_file_action(file_path: str, chat_id: int, caption: str = None) -> dict:
    """Send a file via Telegram."""
    import os
    
    if not file_path:
        return {"error": "file_path required"}
    if not chat_id:
        return {"error": "chat_id required"}
    
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}
    
    try:
        from app.services.telegram_service import telegram_service
        
        # Get file size for logging
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        
        # send_file automatically detects type
        result = await telegram_service.send_file(
            chat_id=chat_id,
            file_path=file_path,
            caption=caption,
        )
        
        return {
            "success": True,
            "file": file_name,
            "size_bytes": file_size,
            "chat_id": chat_id,
        }
        
    except Exception as e:
        return {"error": f"Failed to send file: {e}", "success": False}


def create_workspace_action(task_name: str) -> dict:
    """Create a new workspace for multi-step processing."""
    try:
        from app.services.workspace import workspace_manager
        
        workspace = workspace_manager.create(task_name)
        
        return {
            "success": True,
            "workspace_id": workspace.id,
            "paths": {
                "root": str(workspace.path),
                "input": str(workspace.input_dir),
                "output": str(workspace.output_dir),
                "steps": str(workspace.steps_dir),
            },
            "instructions": "1. Add source files with workspace_add_source. 2. Run commands outputting to steps/ or output/. 3. Send final file from output/.",
        }
    except Exception as e:
        return {"error": f"Failed to create workspace: {e}", "success": False}


def workspace_add_source_action(workspace_id: str, file_path: str) -> dict:
    """Add a source file to workspace."""
    try:
        from app.services.workspace import workspace_manager
        
        workspace = workspace_manager.get(workspace_id)
        if not workspace:
            return {"error": f"Workspace not found: {workspace_id}"}
        
        new_path = workspace.add_source(file_path)
        
        return {
            "success": True,
            "workspace_id": workspace_id,
            "source_path": new_path,
            "message": f"Source file copied to workspace. Use this path for processing: {new_path}",
        }
    except FileNotFoundError as e:
        return {"error": str(e), "success": False}
    except Exception as e:
        return {"error": f"Failed to add source: {e}", "success": False}


def workspace_get_path_action(workspace_id: str) -> dict:
    """Get paths for a workspace."""
    try:
        from app.services.workspace import workspace_manager
        
        workspace = workspace_manager.get(workspace_id)
        if not workspace:
            return {"error": f"Workspace not found: {workspace_id}"}
        
        return {
            "success": True,
            "workspace_id": workspace_id,
            "paths": {
                "root": str(workspace.path),
                "input": str(workspace.input_dir),
                "output": str(workspace.output_dir),
                "steps": str(workspace.steps_dir),
            },
            "source_files": workspace.source_files,
            "steps_completed": len(workspace.steps),
        }
    except Exception as e:
        return {"error": f"Failed to get workspace: {e}", "success": False}
