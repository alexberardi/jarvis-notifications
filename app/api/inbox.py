"""Inbox endpoints — long-form content delivery (deep research results, etc.)."""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import AuthenticatedUser, get_current_user, verify_app_auth
from app.services import inbox_service

router = APIRouter()


# --- Request/Response models ---

class InboxItemCreate(BaseModel):
    household_id: str
    title: str
    summary: str
    body: str
    category: str
    source_service: str
    user_id: int | None = None
    metadata: dict[str, Any] | None = None


class InboxItemResponse(BaseModel):
    id: str
    user_id: int | None
    household_id: str
    title: str
    summary: str
    body: str
    category: str
    source_service: str
    metadata: dict[str, Any] | None = None
    is_read: bool
    created_at: str

    class Config:
        from_attributes = True


class UnreadCountResponse(BaseModel):
    count: int


# --- Helpers ---

def _to_response(item) -> InboxItemResponse:
    metadata = None
    if item.metadata_json:
        try:
            metadata = json.loads(item.metadata_json)
        except (json.JSONDecodeError, TypeError):
            metadata = None

    return InboxItemResponse(
        id=item.id,
        user_id=item.user_id,
        household_id=item.household_id,
        title=item.title,
        summary=item.summary,
        body=item.body,
        category=item.category,
        source_service=item.source_service,
        metadata=metadata,
        is_read=item.is_read,
        created_at=item.created_at.isoformat(),
    )


# --- User-facing endpoints (JWT auth) ---

@router.get("/inbox", response_model=list[InboxItemResponse])
def list_inbox(
    category: str | None = Query(None),
    is_read: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List inbox items for the authenticated user's household."""
    if not user.household_id:
        raise HTTPException(status_code=400, detail="No household_id in token")

    items = inbox_service.list_items(
        db,
        household_id=user.household_id,
        user_id=user.user_id,
        category=category,
        is_read=is_read,
        limit=limit,
        offset=offset,
    )
    return [_to_response(item) for item in items]


@router.get("/inbox/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get unread inbox item count for badge display."""
    if not user.household_id:
        raise HTTPException(status_code=400, detail="No household_id in token")

    count = inbox_service.unread_count(db, user.household_id, user.user_id)
    return UnreadCountResponse(count=count)


@router.get("/inbox/{item_id}", response_model=InboxItemResponse)
def get_inbox_item(
    item_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single inbox item. Auto-marks as read."""
    if not user.household_id:
        raise HTTPException(status_code=400, detail="No household_id in token")

    item = inbox_service.get_item(db, item_id, user.household_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Auto-mark read on open
    if not item.is_read:
        inbox_service.mark_read(db, item_id, user.household_id)
        item.is_read = True

    return _to_response(item)


@router.patch("/inbox/{item_id}/read", response_model=InboxItemResponse)
def mark_item_read(
    item_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly mark an inbox item as read."""
    if not user.household_id:
        raise HTTPException(status_code=400, detail="No household_id in token")

    item = inbox_service.mark_read(db, item_id, user.household_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return _to_response(item)


@router.delete("/inbox/{item_id}", status_code=204)
def delete_inbox_item(
    item_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an inbox item."""
    if not user.household_id:
        raise HTTPException(status_code=400, detail="No household_id in token")

    deleted = inbox_service.delete_item(db, item_id, user.household_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")


# --- Service-to-service endpoint (app-to-app auth) ---

@router.post("/inbox", response_model=InboxItemResponse, dependencies=[Depends(verify_app_auth)])
def create_inbox_item(
    body: InboxItemCreate,
    db: Session = Depends(get_db),
):
    """Create an inbox item (called by command-center or other services)."""
    item = inbox_service.create_item(
        db,
        household_id=body.household_id,
        title=body.title,
        summary=body.summary,
        body=body.body,
        category=body.category,
        source_service=body.source_service,
        user_id=body.user_id,
        metadata=body.metadata,
    )
    return _to_response(item)
