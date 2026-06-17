"""Authentication dependencies for jarvis-notifications.

Three auth patterns:
- User JWT (mobile app): Bearer token validated locally via python-jose
- App-to-app (services): X-Jarvis-App-Id + X-Jarvis-App-Key via jarvis-auth
- Admin (admin endpoints): X-Api-Key header checked against ADMIN_API_KEY
"""

import hmac
from typing import Optional

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import get_settings
from app.core import service_config

security = HTTPBearer(auto_error=True)


class AuthenticatedUser(BaseModel):
    user_id: int
    household_id: str | None = None
    email: str | None = None


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthenticatedUser:
    """Validate Bearer JWT token from mobile app."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.auth_secret_key,
            algorithms=[settings.auth_algorithm],
        )
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        return AuthenticatedUser(
            user_id=int(sub),
            household_id=payload.get("household_id"),
            email=payload.get("email"),
        )
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


async def verify_app_auth(
    request: Request,
    x_jarvis_app_id: Optional[str] = Header(None),
    x_jarvis_app_key: Optional[str] = Header(None),
) -> None:
    """Enforce app-to-app authentication via jarvis-auth /internal/app-ping."""
    if not x_jarvis_app_id or not x_jarvis_app_key:
        raise HTTPException(status_code=401, detail="Missing app credentials")

    try:
        jarvis_auth_base = service_config.get_auth_url()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    app_ping = jarvis_auth_base.rstrip("/") + "/internal/app-ping"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(
                app_ping,
                headers={
                    "X-Jarvis-App-Id": x_jarvis_app_id,
                    "X-Jarvis-App-Key": x_jarvis_app_key,
                },
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Auth service unavailable: {exc}",
            ) from exc

    if resp.status_code != 200:
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid app credentials")
        raise HTTPException(status_code=resp.status_code, detail="App auth failed")

    # Stash calling app in request state
    request.state.calling_app_id = x_jarvis_app_id


def verify_admin_key(
    x_api_key: str = Header(..., alias="X-Api-Key"),
) -> None:
    """Validate admin API key."""
    settings = get_settings()
    if not hmac.compare_digest(x_api_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Invalid admin key")
