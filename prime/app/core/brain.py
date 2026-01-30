"""Alfred's Brain - Claude-powered thinking and decision making.

This is the core intelligence. Every message goes through here.
Claude decides what to do - respond, execute, or both.
"""

import logging
import json
from typing import Optional
from anthropic import AsyncAnthropic

from app.config import settings
from app.grpc_server import daemon_registry, execute_shell, read_file, write_file, list_files

logger = logging.getLogger(__name__)

# Initialize Claude
client = AsyncAnthropic(api_key=settings.claude_api_key)


def get_system_context() -> str:
    """Build the system prompt with current state."""
    
    # Get connected machines
    daemons = daemon_registry.list_all()
    if daemons:
        machines_info = "\n".join([
            f"  - {d.name} ({d.hostname}): {d.status}, CPU: {d.cpu_percent:.1f}%, Mem: {d.memory_percent:.1f}%"
            for d in daemons
        ])
        machines_section = f"""CONNECTED MACHINES:
{machines_info}

You can execute commands on any of these machines."""
    else:
        machines_section = """CONNECTED MACHINES:
  None connected yet.
  
If the user wants to run a command, explain they need to connect a daemon first."""
    
    return f"""You are Alfred, an AI assistant with FULL control over connected machines.

{machines_section}

YOUR CAPABILITIES:
- Execute ANY shell command on connected machines
- Read, write, delete files
- Run as root/sudo
- Docker, Git, system services
- Answer questions, have conversations, be helpful

HOW TO RESPOND:
1. If the user is just chatting or asking questions → respond naturally, be helpful
2. If the user wants to run a command or do something on a machine:
   - If machines are connected → use the execute tool
   - If no machines connected → explain they need to connect a daemon
3. Be concise but not robotic. You're an intelligent assistant, not a command parser.

IMPORTANT:
- You have memory of this conversation
- Be direct and helpful
- Don't ask for unnecessary clarification
- If something fails, explain what happened

When executing commands, prefer the user's default/first connected machine unless they specify otherwise."""


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
    
    # Build tools for Claude
    tools = []
    daemons = daemon_registry.list_all()
    
    if daemons:
        # We have machines to work with
        daemon_names = [d.name for d in daemons]
        
        tools = [
            {
                "name": "execute_shell",
                "description": f"Execute a shell command on a connected machine. Available machines: {', '.join(daemon_names)}",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The shell command to execute"
                        },
                        "machine": {
                            "type": "string",
                            "description": f"Which machine to run on. Options: {', '.join(daemon_names)}",
                            "default": daemon_names[0]
                        },
                        "as_root": {
                            "type": "boolean",
                            "description": "Whether to run with sudo",
                            "default": False
                        }
                    },
                    "required": ["command"]
                }
            },
            {
                "name": "read_file",
                "description": "Read a file from a connected machine",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file"
                        },
                        "machine": {
                            "type": "string",
                            "description": f"Which machine. Options: {', '.join(daemon_names)}",
                            "default": daemon_names[0]
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "write_file",
                "description": "Write content to a file on a connected machine",
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
                            "description": f"Which machine. Options: {', '.join(daemon_names)}",
                            "default": daemon_names[0]
                        }
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "list_files",
                "description": "List files in a directory on a connected machine",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Directory path"
                        },
                        "machine": {
                            "type": "string",
                            "description": f"Which machine. Options: {', '.join(daemon_names)}",
                            "default": daemon_names[0]
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
            tools=tools if tools else None,
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
            messages.append({"role": "assistant", "content": response.content})
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
    
    # Get target machine
    machine = tool_input.get("machine")
    if not machine and daemons:
        machine = daemons[0].name
    
    if not machine:
        return {"error": "No machine specified and none connected"}
    
    if tool_name == "execute_shell":
        command = tool_input.get("command")
        as_root = tool_input.get("as_root", False)
        
        if as_root:
            command = f"sudo {command}"
        
        result = await execute_shell(machine, command)
        return result
    
    elif tool_name == "read_file":
        path = tool_input.get("path")
        result = await read_file(machine, path)
        return result
    
    elif tool_name == "write_file":
        path = tool_input.get("path")
        content = tool_input.get("content")
        result = await write_file(machine, path, content)
        return result
    
    elif tool_name == "list_files":
        path = tool_input.get("path")
        result = await list_files(machine, path)
        return result
    
    else:
        return {"error": f"Unknown tool: {tool_name}"}
