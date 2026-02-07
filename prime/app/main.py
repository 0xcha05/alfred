"""Ultron Prime - Main FastAPI Application."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.api import telegram, daemon

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("🎩 Ultron Prime starting...")
    logger.info(f"   Environment: {settings.environment}")
    logger.info(f"   HTTP port: {settings.port}")
    logger.info(f"   Daemon port: {settings.daemon_port}")
    logger.info(f"   Telegram webhook path: /api/telegram/webhook")
    
    # Log security status
    if settings.telegram_allowed_user_ids:
        logger.info(f"   Telegram whitelist: {len(settings.telegram_allowed_user_ids)} users")
    else:
        logger.warning("   Telegram whitelist: DISABLED (all users allowed)")
    
    if settings.daemon_registration_key:
        logger.info("   Daemon registration: Protected with PSK")
    else:
        logger.warning("   Daemon registration: NO KEY SET")
    
    # Start daemon server (for bidirectional connections)
    from app.grpc_server import start_daemon_server, daemon_registry
    daemon_server = await start_daemon_server(
        host="0.0.0.0",
        port=settings.daemon_port,
    )
    
    # Store server reference for shutdown
    app.state.daemon_server = daemon_server
    app.state.daemon_registry = daemon_registry
    
    # Start event bus
    from app.core.events import event_bus
    from app.core.event_handler import setup_event_handlers
    await event_bus.start()
    setup_event_handlers()
    app.state.event_bus = event_bus
    logger.info("   Event bus: Started")
    
    # Start scheduler
    from app.services.scheduler import scheduler
    await scheduler.start()
    app.state.scheduler = scheduler
    logger.info("   Scheduler: Started")
    
    # Start Telegram polling if enabled (no HTTPS needed)
    if settings.telegram_polling and settings.telegram_token:
        from app.services.telegram_poller import telegram_poller
        await telegram_poller.start()
        app.state.telegram_poller = telegram_poller
        logger.info("   Telegram: POLLING mode (no HTTPS needed)")
    else:
        logger.info("   Telegram: WEBHOOK mode (requires HTTPS)")
    
    logger.info("🎩 Ultron Prime is ready!")
    
    yield
    
    # Shutdown
    logger.info("🎩 Ultron Prime shutting down...")
    
    # Stop scheduler
    if hasattr(app.state, 'scheduler'):
        await app.state.scheduler.stop()
        logger.info("   Scheduler stopped")
    
    # Stop event bus
    if hasattr(app.state, 'event_bus'):
        await app.state.event_bus.stop()
        logger.info("   Event bus stopped")
    
    # Stop Telegram poller
    if hasattr(app.state, 'telegram_poller'):
        await app.state.telegram_poller.stop()
        logger.info("   Telegram poller stopped")
    
    # Stop daemon server
    if hasattr(app.state, 'daemon_server'):
        app.state.daemon_server.close()
        await app.state.daemon_server.wait_closed()
        logger.info("   Daemon server stopped")
    
    # Close telegram client
    from app.services.telegram_service import telegram_service
    await telegram_service.close()


app = FastAPI(
    title="Ultron Prime",
    description="A persistent AI agent across your infrastructure",
    version="0.1.0",
    lifespan=lifespan,
)


# Include routers
app.include_router(telegram.router, prefix="/api/telegram", tags=["telegram"])
app.include_router(daemon.router, prefix="/api/daemon", tags=["daemon"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "ultron-prime",
        "version": "0.1.0",
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Ultron Prime is ready to serve.",
        "docs": "/docs",
    }


@app.post("/setup-webhook")
async def setup_webhook(webhook_url: str):
    """Set up Telegram webhook (for development)."""
    from app.services.telegram_service import telegram_service
    
    full_url = f"{webhook_url}/api/telegram/webhook"
    result = await telegram_service.set_webhook(
        url=full_url,
        secret_token=settings.telegram_webhook_secret or None,
    )
    
    return {
        "webhook_url": full_url,
        "result": result,
    }


@app.get("/webhook-info")
async def webhook_info():
    """Get current Telegram webhook info."""
    from app.services.telegram_service import telegram_service
    return await telegram_service.get_webhook_info()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": str(exc) if settings.environment == "development" else "An error occurred",
        },
    )
