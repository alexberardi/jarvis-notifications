"""Device token CRUD operations."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import DeviceToken

logger = logging.getLogger(__name__)


def register_token(
    db: Session,
    *,
    user_id: int,
    household_id: str,
    push_token: str,
    device_type: str,
    device_name: str | None = None,
) -> DeviceToken:
    """Register or update a push token. Upserts by push_token."""
    existing = db.query(DeviceToken).filter(
        DeviceToken.push_token == push_token
    ).first()

    if existing:
        existing.user_id = user_id
        existing.household_id = household_id
        existing.device_type = device_type
        existing.device_name = device_name
        existing.is_active = True
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        logger.info("Updated token for user %s: %s", user_id, push_token[:20])
        return existing

    token = DeviceToken(
        user_id=user_id,
        household_id=household_id,
        push_token=push_token,
        device_type=device_type,
        device_name=device_name,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    logger.info("Registered token for user %s: %s", user_id, push_token[:20])
    return token


def unregister_token(db: Session, *, push_token: str) -> bool:
    """Deactivate a push token. Returns True if found."""
    token = db.query(DeviceToken).filter(
        DeviceToken.push_token == push_token
    ).first()

    if not token:
        return False

    token.is_active = False
    token.updated_at = datetime.utcnow()
    db.commit()
    logger.info("Deactivated token: %s", push_token[:20])
    return True


def get_user_tokens(db: Session, *, user_id: int) -> list[DeviceToken]:
    """Get all active tokens for a user."""
    return (
        db.query(DeviceToken)
        .filter(DeviceToken.user_id == user_id, DeviceToken.is_active.is_(True))
        .all()
    )


def get_tokens_for_target(
    db: Session, *, target_type: str, target_id: str
) -> list[DeviceToken]:
    """Get active tokens for a notification target (user or household)."""
    query = db.query(DeviceToken).filter(DeviceToken.is_active.is_(True))

    if target_type == "user":
        query = query.filter(DeviceToken.user_id == int(target_id))
    elif target_type == "household":
        query = query.filter(DeviceToken.household_id == target_id)
    else:
        return []

    return query.all()


def deactivate_token_by_push_token(db: Session, *, push_token: str) -> None:
    """Deactivate a token by push_token value (called when relay reports DeviceNotRegistered)."""
    token = db.query(DeviceToken).filter(
        DeviceToken.push_token == push_token
    ).first()
    if token:
        token.is_active = False
        token.updated_at = datetime.utcnow()
        db.commit()
        logger.info("Deactivated invalid token: %s", push_token[:20])


def update_last_used(db: Session, *, push_tokens: list[str]) -> None:
    """Update last_used_at for successfully delivered tokens."""
    now = datetime.utcnow()
    db.query(DeviceToken).filter(
        DeviceToken.push_token.in_(push_tokens)
    ).update({"last_used_at": now}, synchronize_session="fetch")
    db.commit()


def count_tokens(db: Session, *, active_only: bool = True) -> int:
    """Count device tokens."""
    query = db.query(DeviceToken)
    if active_only:
        query = query.filter(DeviceToken.is_active.is_(True))
    return query.count()


def count_tokens_by_household(db: Session) -> list[dict]:
    """Count active tokens grouped by household."""
    from sqlalchemy import func
    results = (
        db.query(
            DeviceToken.household_id,
            func.count(DeviceToken.id).label("count"),
        )
        .filter(DeviceToken.is_active.is_(True))
        .group_by(DeviceToken.household_id)
        .all()
    )
    return [{"household_id": r[0], "count": r[1]} for r in results]
