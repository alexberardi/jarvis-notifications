"""Background cleanup service for pruning old logs and stale tokens."""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import DeviceToken, NotificationLog

logger = logging.getLogger(__name__)

STALE_TOKEN_DAYS = 90  # Deactivate tokens unused for this many days


def cleanup_old_logs(
    retention_days: int | None = None, db: Session | None = None
) -> int:
    """Delete notification_log entries older than retention_days. Returns count deleted."""
    settings = get_settings()
    days = retention_days or settings.notification_log_retention_days
    cutoff = datetime.utcnow() - timedelta(days=days)

    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        count = db.query(NotificationLog).filter(
            NotificationLog.created_at < cutoff
        ).delete(synchronize_session="fetch")
        db.commit()
        if count:
            logger.info("Pruned %d notification log entries older than %d days", count, days)
        return count
    finally:
        if own_session:
            db.close()


def cleanup_stale_tokens(db: Session | None = None) -> int:
    """Deactivate tokens that haven't been used in STALE_TOKEN_DAYS. Returns count deactivated."""
    cutoff = datetime.utcnow() - timedelta(days=STALE_TOKEN_DAYS)

    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        count = db.query(DeviceToken).filter(
            DeviceToken.is_active.is_(True),
            DeviceToken.last_used_at.isnot(None),
            DeviceToken.last_used_at < cutoff,
        ).update(
            {"is_active": False, "updated_at": datetime.utcnow()},
            synchronize_session="fetch",
        )
        db.commit()
        if count:
            logger.info("Deactivated %d stale tokens (unused for %d+ days)", count, STALE_TOKEN_DAYS)
        return count
    finally:
        if own_session:
            db.close()


def run_cleanup() -> dict:
    """Run all cleanup tasks. Returns summary."""
    logs_pruned = cleanup_old_logs()
    tokens_deactivated = cleanup_stale_tokens()
    return {
        "logs_pruned": logs_pruned,
        "tokens_deactivated": tokens_deactivated,
    }


def start_cleanup_task() -> asyncio.Task | None:
    """Start periodic cleanup as an asyncio background task."""
    settings = get_settings()
    interval_hours = settings.token_cleanup_interval_hours

    if interval_hours <= 0:
        logger.info("Cleanup disabled (TOKEN_CLEANUP_INTERVAL_HOURS <= 0)")
        return None

    async def _periodic_cleanup() -> None:
        interval_seconds = interval_hours * 3600
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                result = run_cleanup()
                logger.info("Periodic cleanup complete: %s", result)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Cleanup error: %s", e)

    task = asyncio.create_task(_periodic_cleanup())
    logger.info("Cleanup task started (interval: %dh)", interval_hours)
    return task
