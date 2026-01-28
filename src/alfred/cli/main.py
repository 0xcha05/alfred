"""Alfred CLI - interact with Alfred Prime from the command line."""

import argparse
import asyncio
import sys

import httpx

DEFAULT_URL = "http://localhost:8000"


async def send_message(url: str, message: str, user_id: str = "cli-user") -> str:
    """Send a message to Alfred Prime and return the response."""
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{url}/api/message",
            json={
                "message": message,
                "user_id": user_id,
                "channel": "cli",
            },
        )
        response.raise_for_status()
        return response.json()["response"]


async def check_status(url: str) -> dict:
    """Check Alfred Prime status."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{url}/status")
        response.raise_for_status()
        return response.json()


async def interactive_mode(url: str, user_id: str) -> None:
    """Run in interactive mode."""
    print("Alfred CLI - Interactive Mode")
    print(f"Connected to: {url}")
    print("Type 'exit' or 'quit' to leave\n")

    while True:
        try:
            message = input("You: ").strip()

            if not message:
                continue

            if message.lower() in ("exit", "quit"):
                print("Goodbye!")
                break

            response = await send_message(url, message, user_id)
            print(f"\nAlfred: {response}\n")

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except httpx.ConnectError:
            print(f"Error: Cannot connect to Alfred Prime at {url}")
            print("Make sure Alfred Prime is running.")
            break
        except Exception as e:
            print(f"Error: {e}")


async def single_message(url: str, message: str, user_id: str) -> None:
    """Send a single message and print the response."""
    try:
        response = await send_message(url, message, user_id)
        print(response)
    except httpx.ConnectError:
        print(f"Error: Cannot connect to Alfred Prime at {url}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


async def show_status(url: str) -> None:
    """Show Alfred Prime status."""
    try:
        status = await check_status(url)
        print("Alfred Prime Status")
        print("=" * 40)
        print(f"Online Daemons: {status.get('online_daemons', 0)}")

        daemons = status.get("daemons", [])
        if daemons:
            print("\nRegistered Machines:")
            for d in daemons:
                caps = ", ".join(d.get("capabilities", []))
                print(f"  - {d['name']} ({d['type']}): {caps}")
        else:
            print("\nNo machines registered.")

    except httpx.ConnectError:
        print(f"Error: Cannot connect to Alfred Prime at {url}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Alfred CLI - interact with Alfred Prime",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  alfred-cli                     # Interactive mode
  alfred-cli "run the tests"     # Single message
  alfred-cli --status            # Check status
  alfred-cli -u http://host:8000 "list files"
        """,
    )

    parser.add_argument(
        "message",
        nargs="?",
        help="Message to send (omit for interactive mode)",
    )
    parser.add_argument(
        "-u", "--url",
        default=DEFAULT_URL,
        help=f"Alfred Prime URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--user-id",
        default="cli-user",
        help="User ID for the conversation",
    )
    parser.add_argument(
        "-s", "--status",
        action="store_true",
        help="Show Alfred Prime status",
    )

    args = parser.parse_args()

    if args.status:
        asyncio.run(show_status(args.url))
    elif args.message:
        asyncio.run(single_message(args.url, args.message, args.user_id))
    else:
        asyncio.run(interactive_mode(args.url, args.user_id))


if __name__ == "__main__":
    main()
