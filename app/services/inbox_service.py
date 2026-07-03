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


def get_item(
    db: Session, item_id: str, household_id: str, user_id: int | None = None
) -> InboxItem | None:
    """Get a single inbox item by ID.

    Scoped to the household and — when ``user_id`` is provided — to items visible
    to that user: their own personal items OR household-wide items (user_id=None).
    A personal item belonging to another household member is NOT returned, so a
    member who learns another's item UUID can't read it (intra-household IDOR).
    """
    query = db.query(InboxItem).filter(
        InboxItem.id == item_id, InboxItem.household_id == household_id
    )
    if user_id is not None:
        query = query.filter(
            (InboxItem.user_id == user_id) | (InboxItem.user_id.is_(None))
        )
    return query.first()


def mark_read(
    db: Session, item_id: str, household_id: str, user_id: int | None = None
) -> InboxItem | None:
    """Mark an inbox item as read (scoped to the caller's visibility)."""
    item = get_item(db, item_id, household_id, user_id)
    if item and not item.is_read:
        item.is_read = True
        db.commit()
        db.refresh(item)
    return item


def delete_item(
    db: Session, item_id: str, household_id: str, user_id: int | None = None
) -> bool:
    """Delete an inbox item (scoped to the caller's visibility)."""
    item = get_item(db, item_id, household_id, user_id)
    if not item:
        return False
    db.delete(item)
    db.commit()
    return True


def _scoped_query(db: Session, household_id: str, user_id: int | None, ids: list[str]):
    query = db.query(InboxItem).filter(
        InboxItem.household_id == household_id,
        InboxItem.id.in_(ids),
    )
    if user_id is not None:
        query = query.filter(
            (InboxItem.user_id == user_id) | (InboxItem.user_id.is_(None))
        )
    return query


def bulk_mark_read(
    db: Session,
    *,
    household_id: str,
    user_id: int | None,
    ids: list[str],
) -> int:
    """Mark multiple inbox items as read. Returns count actually updated."""
    if not ids:
        return 0
    items = _scoped_query(db, household_id, user_id, ids).filter(InboxItem.is_read == False).all()
    for item in items:
        item.is_read = True
    if items:
        db.commit()
    return len(items)


def bulk_delete(
    db: Session,
    *,
    household_id: str,
    user_id: int | None,
    ids: list[str],
) -> int:
    """Delete multiple inbox items. Returns count actually deleted."""
    if not ids:
        return 0
    items = _scoped_query(db, household_id, user_id, ids).all()
    for item in items:
        db.delete(item)
    if items:
        db.commit()
    return len(items)


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
