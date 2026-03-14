"""Inbox item CRUD operations."""

import json
import logging
import uuid
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import InboxItem

logger = logging.getLogger(__name__)


def create_item(
    db: Session,
    *,
    household_id: str,
    title: str,
    summary: str,
    body: str,
    category: str,
    source_service: str,
    user_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> InboxItem:
    """Create a new inbox item."""
    item = InboxItem(
        id=str(uuid.uuid4()),
        user_id=user_id,
        household_id=household_id,
        title=title,
        summary=summary,
        body=body,
        category=category,
        source_service=source_service,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info("Created inbox item %s (%s) for household %s", item.id, category, household_id)
    return item


def list_items(
    db: Session,
    *,
    household_id: str,
    user_id: int | None = None,
    category: str | None = None,
    is_read: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[InboxItem]:
    """List inbox items for a household, newest first."""
    query = db.query(InboxItem).filter(InboxItem.household_id == household_id)

    if user_id is not None:
        # Show items targeted to this user OR to the whole household (user_id=None)
        query = query.filter(
            (InboxItem.user_id == user_id) | (InboxItem.user_id.is_(None))
        )
    if category is not None:
        query = query.filter(InboxItem.category == category)
    if is_read is not None:
        query = query.filter(InboxItem.is_read == is_read)

    return query.order_by(desc(InboxItem.created_at)).offset(offset).limit(limit).all()


def get_item(db: Session, item_id: str, household_id: str) -> InboxItem | None:
    """Get a single inbox item by ID (scoped to household)."""
    return (
        db.query(InboxItem)
        .filter(InboxItem.id == item_id, InboxItem.household_id == household_id)
        .first()
    )


def mark_read(db: Session, item_id: str, household_id: str) -> InboxItem | None:
    """Mark an inbox item as read."""
    item = get_item(db, item_id, household_id)
    if item and not item.is_read:
        item.is_read = True
        db.commit()
        db.refresh(item)
    return item


def delete_item(db: Session, item_id: str, household_id: str) -> bool:
    """Delete an inbox item."""
    item = get_item(db, item_id, household_id)
    if not item:
        return False
    db.delete(item)
    db.commit()
    return True


def unread_count(db: Session, household_id: str, user_id: int | None = None) -> int:
    """Count unread inbox items."""
    query = db.query(InboxItem).filter(
        InboxItem.household_id == household_id,
        InboxItem.is_read == False,
    )
    if user_id is not None:
        query = query.filter(
            (InboxItem.user_id == user_id) | (InboxItem.user_id.is_(None))
        )
    return query.count()
