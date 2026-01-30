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


def get_system_context() -> str:
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
    
    return f"""You are Alfred, an AI assistant with FULL control over machines.

{machines_section}

YOUR CAPABILITIES:
- Execute ANY shell command on any machine (including this server - "prime")
- Read, write, delete files
- Run as root/sudo
- Docker, Git, system services
- Answer questions, have conversations, be helpful

HOW TO RESPOND:
1. If the user is just chatting or asking questions → respond naturally, be helpful
2. If the user wants to run a command:
   - Use the execute tool with the appropriate machine
   - For "prime" or "this server" → run locally
   - For other machines → route to connected daemon
3. Be concise but not robotic. You're an intelligent assistant, not a command parser.

IMPORTANT:
- You have memory of this conversation
- Be direct and helpful
- Don't ask for unnecessary clarification
- If something fails, explain what happened
- You are running on the Prime server (EC2) - you can always execute commands here

When executing commands, prefer "prime" (this server) unless user specifies a different machine."""


async def think(
    message: str,
    chat_id: int,
    conversation_history: Optional[list] = None,
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
        }
    ]
    
    # Build messages
    messages = []
    
    # Add conversation history if available
    if conversation_history:
        messages.extend(conversation_history)
    
    # Add current message
    messages.append({"role": "user", "content": message})
    
    try:
        # Call Claude
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=get_system_context(),
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
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=get_system_context(),
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
