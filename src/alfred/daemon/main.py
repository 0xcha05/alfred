"""Daemon entry point and API server."""

import asyncio
import socket
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

from alfred.common import get_logger, setup_logging
from alfred.common.models import Capability, DaemonInfo, TaskRequest, TaskResult
from alfred.config import get_daemon_settings
from alfred.daemon.capabilities import FilesCapability, ShellCapability
from alfred.daemon.executor import TaskExecutor

logger = get_logger(__name__)


class DaemonState:
    """Global daemon state."""

    executor: TaskExecutor
    settings: any
    registered: bool = False


state = DaemonState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    settings = get_daemon_settings()
    setup_logging(settings.log_level if hasattr(settings, 'log_level') else "INFO")

    state.settings = settings
    state.executor = TaskExecutor()

    # Register capabilities based on settings
    if "shell" in settings.capabilities:
        state.executor.register_capability(ShellCapability(settings.work_dir))
    if "files" in settings.capabilities:
        state.executor.register_capability(FilesCapability(settings.work_dir))

    logger.info(
        "daemon_starting",
        name=settings.name,
        capabilities=state.executor.get_capabilities(),
    )

    # Register with Alfred Prime
    asyncio.create_task(register_with_prime())

    # Start heartbeat loop
    asyncio.create_task(heartbeat_loop())

    yield

    logger.info("daemon_stopping", name=settings.name)


app = FastAPI(
    title="Alfred Daemon",
    description="Lightweight agent for Alfred Prime",
    lifespan=lifespan,
)


def verify_auth(authorization: str | None) -> None:
    """Verify the authorization header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization")

    expected = f"Bearer {state.settings.secret_key.get_secret_value()}"
    if authorization != expected:
        raise HTTPException(status_code=403, detail="Invalid authorization")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "name": state.settings.name,
        "capabilities": state.executor.get_capabilities(),
    }


@app.get("/info")
async def info(authorization: str | None = Header(None)):
    """Get daemon information."""
    verify_auth(authorization)
    return DaemonInfo(
        name=state.settings.name,
        machine_type=state.settings.machine_type,
        capabilities=[Capability(c) for c in state.executor.get_capabilities()],
        hostname=socket.gethostname(),
        ip_address=get_local_ip(),
        port=state.settings.port,
        online=True,
    )


class ExecuteRequest(BaseModel):
    """Request to execute a task."""

    task_id: str
    action: str
    params: dict = {}
    timeout: int = 300


@app.post("/execute", response_model=TaskResult)
async def execute(request: ExecuteRequest, authorization: str | None = Header(None)):
    """Execute a task."""
    verify_auth(authorization)

    result = await state.executor.execute(
        task_id=request.task_id,
        action=request.action,
        params=request.params,
    )

    return result


@app.get("/actions")
async def list_actions(authorization: str | None = Header(None)):
    """List available actions."""
    verify_auth(authorization)
    return {"actions": state.executor.get_actions()}


async def register_with_prime():
    """Register this daemon with Alfred Prime."""
    settings = state.settings

    daemon_info = DaemonInfo(
        name=settings.name,
        machine_type=settings.machine_type,
        capabilities=[Capability(c) for c in state.executor.get_capabilities()],
        hostname=socket.gethostname(),
        ip_address=get_local_ip(),
        port=settings.port,
        online=True,
    )

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{settings.prime_url}/api/daemons/register",
                json=daemon_info.model_dump(mode="json"),
                headers={"Authorization": f"Bearer {settings.secret_key.get_secret_value()}"},
                timeout=10,
            )
            if response.status_code == 200:
                state.registered = True
                logger.info("registered_with_prime", name=settings.name)
            else:
                logger.warning(
                    "registration_failed",
                    status=response.status_code,
                    detail=response.text,
                )
        except Exception as e:
            logger.warning("registration_error", error=str(e))


async def heartbeat_loop():
    """Send periodic heartbeats to Alfred Prime."""
    settings = state.settings

    while True:
        await asyncio.sleep(60)  # Every minute

        if not state.registered:
            await register_with_prime()
            continue

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{settings.prime_url}/api/daemons/{settings.name}/heartbeat",
                    headers={"Authorization": f"Bearer {settings.secret_key.get_secret_value()}"},
                    timeout=10,
                )
                if response.status_code != 200:
                    logger.warning("heartbeat_failed", status=response.status_code)
                    state.registered = False
            except Exception as e:
                logger.warning("heartbeat_error", error=str(e))
                state.registered = False


def get_local_ip() -> str:
    """Get the local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    """Run the daemon server."""
    import uvicorn

    settings = get_daemon_settings()
    uvicorn.run(
        "alfred.daemon.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
