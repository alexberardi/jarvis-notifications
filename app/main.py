import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core import service_config
from app.db import Base, engine
from app.api.tokens import router as tokens_router
from app.api.notify import router as notify_router
from app.api.admin import router as admin_router
from app.api.inbox import router as inbox_router

logger = logging.getLogger(__name__)


def _setup_remote_logging() -> None:
    """Initialize remote logging via jarvis-log-client if configured."""
    app_key = os.getenv("JARVIS_APP_KEY")
    if not app_key:
        return

    try:
        from jarvis_log_client import JarvisLogHandler

        remote_level_name = os.getenv("JARVIS_LOG_REMOTE_LEVEL", "INFO").upper()
        remote_level = getattr(logging, remote_level_name, logging.INFO)

        # Filter out uvicorn access logs from remote shipping —
        # high-frequency polling (e.g., inbox) floods jarvis-logs.
        class _ExcludeAccessLogs(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                return record.name != "uvicorn.access"

        handler = JarvisLogHandler(service="jarvis-notifications")
        handler.setLevel(remote_level)
        handler.addFilter(_ExcludeAccessLogs())

        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(remote_level)

        # Even at DEBUG, third-party request-by-request chatter swamps
        # the actual signal. Keep these at WARNING regardless of level.
        for noisy in ("httpx", "httpcore", "urllib3", "sqlalchemy.engine"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

        logger.info("Remote logging initialized (level=%s)", remote_level_name)
    except ImportError:
        logger.info("jarvis-log-client not installed, using console logging only")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    get_settings().validate_security()  # fail closed on insecure auth secrets
    service_config.init()
    _setup_remote_logging()
    Base.metadata.create_all(bind=engine)

    # Start cleanup background task
    from app.services.cleanup_service import start_cleanup_task
    cleanup_task = start_cleanup_task()

    logger.info("jarvis-notifications started on port %s", get_settings().notifications_port)
    yield

    # Shutdown
    if cleanup_task:
        cleanup_task.cancel()
    service_config.shutdown()
    logger.info("jarvis-notifications shutdown complete")


app = FastAPI(
    title="Jarvis Notifications",
    description="Push notification service for the Jarvis ecosystem",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: wildcard origin is acceptable here because every endpoint authenticates
# via header (bearer JWT / admin token), not cookies — so credentials mode is off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(tokens_router, prefix="/api/v0", tags=["tokens"])
app.include_router(notify_router, prefix="/api/v0", tags=["notify"])
app.include_router(admin_router, prefix="/api/v0/admin", tags=["admin"])
app.include_router(inbox_router, prefix="/api/v0", tags=["inbox"])


@app.get("/info")
def info():
    """Unauthenticated service identity endpoint for network discovery."""
    return {"service": "jarvis-notifications"}


@app.get("/health")
def health():
    """Health check."""
    return {"status": "ok", "service": "jarvis-notifications"}


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host="0.0.0.0", port=settings.notifications_port)
