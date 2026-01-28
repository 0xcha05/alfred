"""Alfred Prime entry point and API server."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

from alfred.common import get_logger, setup_logging
from alfred.common.models import DaemonInfo, TaskResult
from alfred.config import get_settings
from alfred.memory import get_db, init_db, MemoryStore
from alfred.prime.brain import AlfredBrain
from alfred.prime.channels.telegram import TelegramChannel
from alfred.prime.intent import IntentParser
from alfred.prime.router import TaskRouter

logger = get_logger(__name__)


class PrimeState:
    """Global Alfred Prime state."""

    brain: AlfredBrain
    router: TaskRouter
    telegram: TelegramChannel | None = None
    settings: Any


state = PrimeState()


def verify_daemon_auth(authorization: str | None = Header(None)) -> None:
    """Verify daemon authorization."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization")

    expected = f"Bearer {state.settings.daemon_secret_key.get_secret_value()}"
    if authorization != expected:
        raise HTTPException(status_code=403, detail="Invalid authorization")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    settings = get_settings()
    setup_logging(settings.log_level)

    state.settings = settings

    # Initialize database
    await init_db()
    logger.info("database_initialized")

    # Initialize components
    state.router = TaskRouter(settings.daemon_secret_key.get_secret_value())
    intent_parser = IntentParser()
    state.brain = AlfredBrain(state.router, intent_parser)

    # Start Telegram bot if configured
    if settings.telegram_bot_token:
        state.telegram = TelegramChannel(
            token=settings.telegram_bot_token.get_secret_value(),
            message_handler=handle_message,
        )
        await state.telegram.start()

    logger.info("alfred_prime_started")

    yield

    # Cleanup
    if state.telegram:
        await state.telegram.stop()

    await state.router.close()
    logger.info("alfred_prime_stopped")


app = FastAPI(
    title="Alfred Prime",
    description="The brain of the Alfred system",
    lifespan=lifespan,
)


async def handle_message(message: str, user_id: str, channel: str) -> str:
    """Handle an incoming message from any channel."""
    async with get_db() as session:
        memory = MemoryStore(session)
        return await state.brain.process_message(
            user_message=message,
            user_id=user_id,
            channel=channel,
            memory=memory,
        )


# Health and status endpoints


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "alfred-prime"}


@app.get("/status")
async def status():
    """Get Alfred Prime status."""
    return await state.brain.get_status()


# Daemon management endpoints


@app.post("/api/daemons/register")
async def register_daemon(
    info: DaemonInfo,
    _: None = Depends(verify_daemon_auth),
):
    """Register a daemon with Alfred Prime."""
    state.router.register_daemon(info)

    # Also persist to database
    async with get_db() as session:
        memory = MemoryStore(session)
        await memory.register_machine(info)

    return {"status": "registered", "name": info.name}


@app.post("/api/daemons/{name}/heartbeat")
async def daemon_heartbeat(
    name: str,
    _: None = Depends(verify_daemon_auth),
):
    """Receive heartbeat from a daemon."""
    if state.router.update_daemon_heartbeat(name):
        async with get_db() as session:
            memory = MemoryStore(session)
            await memory.update_machine_heartbeat(name)
        return {"status": "ok"}

    raise HTTPException(status_code=404, detail="Daemon not found")


@app.delete("/api/daemons/{name}")
async def unregister_daemon(
    name: str,
    _: None = Depends(verify_daemon_auth),
):
    """Unregister a daemon."""
    state.router.unregister_daemon(name)

    async with get_db() as session:
        memory = MemoryStore(session)
        await memory.mark_machine_offline(name)

    return {"status": "unregistered", "name": name}


@app.get("/api/daemons")
async def list_daemons(_: None = Depends(verify_daemon_auth)):
    """List all registered daemons."""
    daemons = state.router.get_online_daemons()
    return {
        "daemons": [
            {
                "name": d.name,
                "machine_type": d.machine_type,
                "capabilities": [c.value for c in d.capabilities],
                "hostname": d.hostname,
                "online": d.online,
                "last_seen": d.last_seen.isoformat(),
            }
            for d in daemons
        ]
    }


# Message handling endpoint (for CLI and other integrations)


class MessageRequest(BaseModel):
    """Request to process a message."""

    message: str
    user_id: str = "cli-user"
    channel: str = "cli"


class MessageResponse(BaseModel):
    """Response from message processing."""

    response: str


@app.post("/api/message", response_model=MessageResponse)
async def process_message(request: MessageRequest):
    """Process a message from any channel."""
    response = await handle_message(
        message=request.message,
        user_id=request.user_id,
        channel=request.channel,
    )
    return MessageResponse(response=response)


# Task execution endpoint (for direct task dispatch)


class TaskDispatchRequest(BaseModel):
    """Request to dispatch a task."""

    action: str
    params: dict = {}
    machine: str | None = None


@app.post("/api/tasks/dispatch", response_model=TaskResult)
async def dispatch_task(
    request: TaskDispatchRequest,
    _: None = Depends(verify_daemon_auth),
):
    """Dispatch a task directly to a daemon."""
    result = await state.router.dispatch(
        action=request.action,
        params=request.params,
        machine=request.machine,
    )
    return result


def main():
    """Run Alfred Prime server."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "alfred.prime.main:app",
        host=settings.host,
        port=settings.prime_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
