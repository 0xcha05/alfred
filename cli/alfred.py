#!/usr/bin/env python3
"""Alfred CLI - Direct terminal interface to Alfred Prime."""

import argparse
import asyncio
import sys
import os
import json
from typing import Optional

import httpx

# Default Prime URL
DEFAULT_PRIME_URL = os.environ.get("ALFRED_PRIME_URL", "http://localhost:8000")


class AlfredCLI:
    """CLI client for Alfred Prime."""
    
    def __init__(self, prime_url: str = DEFAULT_PRIME_URL):
        self.prime_url = prime_url.rstrip("/")
        self.client = httpx.Client(timeout=120.0)
    
    def health(self) -> dict:
        """Check Prime health."""
        response = self.client.get(f"{self.prime_url}/health")
        response.raise_for_status()
        return response.json()
    
    def list_daemons(self) -> dict:
        """List connected daemons."""
        response = self.client.get(f"{self.prime_url}/api/daemon/list")
        response.raise_for_status()
        return response.json()
    
    def execute(self, message: str) -> dict:
        """Execute a command (simulate sending a message)."""
        # This would normally go through the intent parser
        # For CLI, we'll create a direct execute endpoint
        response = self.client.post(
            f"{self.prime_url}/api/execute",
            json={"message": message},
        )
        if response.status_code == 404:
            # Fallback: just parse and show what would happen
            return {"message": message, "note": "Direct execute endpoint not implemented. Use Telegram."}
        response.raise_for_status()
        return response.json()
    
    def status(self) -> dict:
        """Get status of running tasks."""
        response = self.client.get(f"{self.prime_url}/api/status")
        if response.status_code == 404:
            return {"status": "ok", "note": "Status endpoint not implemented yet"}
        response.raise_for_status()
        return response.json()


def cmd_health(args, cli: AlfredCLI):
    """Check if Prime is healthy."""
    try:
        result = cli.health()
        print(f"✓ Alfred Prime is {result.get('status', 'unknown')}")
        print(f"  Version: {result.get('version', 'unknown')}")
    except httpx.ConnectError:
        print(f"✗ Cannot connect to Alfred Prime at {cli.prime_url}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


def cmd_machines(args, cli: AlfredCLI):
    """List connected daemons."""
    try:
        result = cli.list_daemons()
        daemons = result.get("daemons", [])
        
        if not daemons:
            print("No daemons connected.")
            return
        
        print(f"Connected daemons ({len(daemons)}):\n")
        for d in daemons:
            status_icon = "●" if d.get("status") == "connected" else "○"
            print(f"  {status_icon} {d.get('id')} - {d.get('name')}")
            print(f"    Hostname: {d.get('hostname')}")
            print(f"    Capabilities: {', '.join(d.get('capabilities', []))}")
            print(f"    Status: {d.get('status')}")
            print()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_execute(args, cli: AlfredCLI):
    """Execute a command."""
    message = " ".join(args.command)
    
    if not message:
        print("Error: No command provided")
        sys.exit(1)
    
    try:
        result = cli.execute(message)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_status(args, cli: AlfredCLI):
    """Show status of running tasks."""
    try:
        result = cli.status()
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_interactive(args, cli: AlfredCLI):
    """Start interactive mode."""
    print("Alfred CLI - Interactive Mode")
    print("Type 'exit' or 'quit' to exit, 'help' for commands")
    print()
    
    try:
        import readline  # For history support
    except ImportError:
        pass
    
    while True:
        try:
            line = input("alfred> ").strip()
            
            if not line:
                continue
            
            if line.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break
            
            if line.lower() == "help":
                print("""
Commands:
  machines    - List connected daemons
  status      - Show running tasks
  health      - Check Prime status
  exit/quit   - Exit interactive mode
  
Or type any command to execute:
  ls -la
  run the tests
  check disk space
""")
                continue
            
            if line.lower() == "machines":
                cmd_machines(args, cli)
                continue
            
            if line.lower() == "status":
                cmd_status(args, cli)
                continue
            
            if line.lower() == "health":
                cmd_health(args, cli)
                continue
            
            # Execute as command
            result = cli.execute(line)
            
            if isinstance(result, dict):
                if "output" in result:
                    print(result["output"])
                elif "error" in result:
                    print(f"Error: {result['error']}")
                else:
                    print(json.dumps(result, indent=2))
            else:
                print(result)
            
        except KeyboardInterrupt:
            print("\nUse 'exit' to quit")
        except EOFError:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Alfred CLI - Command your infrastructure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  alfred "run the tests"         Execute a command
  alfred machines                List connected daemons
  alfred status                  Show running tasks
  alfred -i                      Start interactive mode
  alfred --url http://host:8000  Use different Prime URL
""",
    )
    
    parser.add_argument(
        "--url",
        default=DEFAULT_PRIME_URL,
        help=f"Alfred Prime URL (default: {DEFAULT_PRIME_URL})",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Start interactive mode",
    )
    parser.add_argument(
        "command",
        nargs="*",
        help="Command to execute",
    )
    
    args = parser.parse_args()
    cli = AlfredCLI(args.url)
    
    # Check which command to run
    if args.interactive:
        cmd_interactive(args, cli)
    elif args.command:
        cmd_text = args.command[0].lower() if args.command else ""
        
        if cmd_text == "health":
            cmd_health(args, cli)
        elif cmd_text == "machines":
            cmd_machines(args, cli)
        elif cmd_text == "status":
            cmd_status(args, cli)
        else:
            cmd_execute(args, cli)
    else:
        # No command, start interactive mode
        cmd_interactive(args, cli)


if __name__ == "__main__":
    main()
