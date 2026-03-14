"""Notification sending endpoints — called by services (app-to-app auth)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import verify_app_auth
from app.services import notification_service

router = APIRouter()


class NotifyRequest(BaseModel):
    target_type: str  # "user" or "household"
    target_id: str
    title: str
    body: str
    data: dict | None = None
    priority: str = "default"
    category: str | None = None


class NotifyResponse(BaseModel):
    id: str
    delivery_status: str
    token_count: int
    success_count: int
    failure_count: int

    class Config:
        from_attributes = True


class BatchNotifyRequest(BaseModel):
    notifications: list[NotifyRequest]


@router.post("/notify", response_model=NotifyResponse, dependencies=[Depends(verify_app_auth)])
async def send_notification(
    body: NotifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Send a push notification to a target (user or household)."""
    if body.target_type not in ("user", "household"):
        raise HTTPException(status_code=400, detail="target_type must be 'user' or 'household'")

    if body.priority not in ("default", "high"):
        raise HTTPException(status_code=400, detail="priority must be 'default' or 'high'")

    source_service = getattr(request.state, "calling_app_id", "unknown")

    log_entry = await notification_service.send_notification(
        db,
        source_service=source_service,
        target_type=body.target_type,
        target_id=body.target_id,
        title=body.title,
        body=body.body,
        data=body.data,
        priority=body.priority,
        category=body.category,
    )
    return log_entry


@router.post("/notify/batch", response_model=list[NotifyResponse], dependencies=[Depends(verify_app_auth)])
async def send_batch(
    body: BatchNotifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Send multiple notifications in one call."""
    if len(body.notifications) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 notifications per batch")

    source_service = getattr(request.state, "calling_app_id", "unknown")
    results = []

    for notification in body.notifications:
        if notification.target_type not in ("user", "household"):
            raise HTTPException(
                status_code=400,
                detail=f"target_type must be 'user' or 'household', got '{notification.target_type}'",
            )

        log_entry = await notification_service.send_notification(
            db,
            source_service=source_service,
            target_type=notification.target_type,
            target_id=notification.target_id,
            title=notification.title,
            body=notification.body,
            data=notification.data,
            priority=notification.priority,
            category=notification.category,
        )
        results.append(log_entry)

    return results
