"""Token registration endpoints — called by mobile app (JWT auth)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import AuthenticatedUser, get_current_user
from app.services import account_service, token_service

router = APIRouter()


class RegisterTokenRequest(BaseModel):
    push_token: str
    device_type: str  # "ios" or "android"
    device_name: str | None = None


class UnregisterTokenRequest(BaseModel):
    push_token: str


class TokenResponse(BaseModel):
    id: str
    push_token: str
    device_type: str
    device_name: str | None
    is_active: bool

    class Config:
        from_attributes = True


@router.post("/tokens", response_model=TokenResponse)
def register_token(
    body: RegisterTokenRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register a push token for the authenticated user."""
    if body.device_type not in ("ios", "android"):
        raise HTTPException(status_code=400, detail="device_type must be 'ios' or 'android'")

    if not user.household_id:
        raise HTTPException(status_code=400, detail="User JWT missing household_id claim")

    token = token_service.register_token(
        db,
        user_id=user.user_id,
        household_id=user.household_id,
        push_token=body.push_token,
        device_type=body.device_type,
        device_name=body.device_name,
    )
    return token


@router.delete("/tokens")
def unregister_token(
    body: UnregisterTokenRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unregister a push token (called on logout)."""
    found = token_service.unregister_token(db, push_token=body.push_token)
    if not found:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "ok"}


@router.get("/tokens/me", response_model=list[TokenResponse])
def list_my_tokens(
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List active tokens for the authenticated user."""
    tokens = token_service.get_user_tokens(db, user_id=user.user_id)
    return tokens


@router.delete("/me/data", status_code=204)
def purge_my_data(
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Self-scoped purge: delete all notification data for the caller.

    Removes every device token and inbox item owned by the authenticated user.
    Called by jarvis-auth's account-deletion flow (DELETE /auth/me forwards the
    user token here). Idempotent — returns 204 even with no rows to delete.
    """
    account_service.purge_user_data(db, user_id=user.user_id)
