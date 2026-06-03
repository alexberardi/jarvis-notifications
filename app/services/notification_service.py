"""Core notification send logic with relay forwarding, dedup, and retry."""

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.models import NotificationLog
from app.services.token_service import (
    deactivate_token_by_push_token,
    get_tokens_for_target,
    update_last_used,
)

logger = logging.getLogger(__name__)

# In-memory dedup cache: key -> timestamp
_dedup_cache: dict[str, datetime] = {}
DEDUP_WINDOW_SECONDS = 60

# In-memory retry queue
_retry_queue: asyncio.Queue | None = None
MAX_RETRIES = 3
RETRY_DELAYS = [30, 60, 120]  # seconds

# Module-level cache of household JWTs minted by the relay's /v1/register.
# Process-local — fine because /v1/register is idempotent and cheap, so a
# restart costs one extra registration call per active household.
_relay_jwt_cache: dict[str, str] = {}
_relay_jwt_lock: asyncio.Lock | None = None


@dataclass
class RetryItem:
    tokens: list[str]
    title: str
    body: str
    data: dict | None
    priority: str
    household_id: str
    attempt: int = 0


def _dedup_key(
    source_service: str,
    target_id: str,
    title: str,
    body: str,
    category: str | None,
) -> str:
    """Generate dedup key from notification attributes."""
    raw = f"{source_service}:{target_id}:{title}:{body}:{category or ''}"
    return hashlib.md5(raw.encode()).hexdigest()


def _is_duplicate(key: str) -> bool:
    """Check if notification was sent recently (within dedup window)."""
    now = datetime.utcnow()
    # Clean expired entries
    expired = [k for k, t in _dedup_cache.items() if (now - t).total_seconds() > DEDUP_WINDOW_SECONDS]
    for k in expired:
        del _dedup_cache[k]

    if key in _dedup_cache:
        return True

    _dedup_cache[key] = now
    return False


async def send_notification(
    db: Session,
    *,
    source_service: str,
    target_type: str,
    target_id: str,
    title: str,
    body: str,
    data: dict | None = None,
    priority: str = "default",
    category: str | None = None,
) -> NotificationLog:
    """Send a push notification to a target (user or household).

    1. Resolve tokens for the target
    2. Check dedup
    3. Forward to relay (if configured)
    4. Log the result
    """
    # Check dedup
    key = _dedup_key(source_service, target_id, title, body, category)
    if _is_duplicate(key):
        logger.info("Duplicate notification suppressed: %s -> %s", source_service, target_id)
        log_entry = NotificationLog(
            source_service=source_service,
            target_type=target_type,
            target_id=target_id,
            title=title,
            body=body,
            data=json.dumps(data) if data else None,
            category=category,
            token_count=0,
            success_count=0,
            failure_count=0,
            delivery_status="skipped",
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        return log_entry

    # Resolve tokens
    tokens = get_tokens_for_target(db, target_type=target_type, target_id=target_id)
    push_tokens = [t.push_token for t in tokens]

    if not push_tokens:
        logger.info("No active tokens for %s:%s", target_type, target_id)
        log_entry = NotificationLog(
            source_service=source_service,
            target_type=target_type,
            target_id=target_id,
            title=title,
            body=body,
            data=json.dumps(data) if data else None,
            category=category,
            token_count=0,
            success_count=0,
            failure_count=0,
            delivery_status="skipped",
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        return log_entry

    # Get household_id from first token (all tokens for a target share household)
    household_id = tokens[0].household_id

    # Deliver via relay
    results = await _deliver_via_relay(
        tokens=push_tokens,
        title=title,
        body=body,
        data=data,
        priority=priority,
        household_id=household_id,
    )

    # Process results
    success_count = 0
    failure_count = 0
    successful_tokens: list[str] = []

    for result in results:
        if result.get("status") == "ok":
            success_count += 1
            successful_tokens.append(result.get("token", ""))
        elif result.get("status") == "skipped":
            pass  # Relay not configured
        else:
            failure_count += 1
            # Deactivate tokens that are no longer registered
            if result.get("error") == "DeviceNotRegistered":
                token_val = result.get("token", "")
                if token_val:
                    deactivate_token_by_push_token(db, push_token=token_val)

    # Update last_used_at for successful deliveries
    if successful_tokens:
        update_last_used(db, push_tokens=successful_tokens)

    # Determine delivery status
    skipped = all(r.get("status") == "skipped" for r in results)
    if skipped:
        delivery_status = "skipped"
    elif failure_count == 0:
        delivery_status = "delivered"
    elif success_count == 0:
        delivery_status = "failed"
    else:
        delivery_status = "partial"

    log_entry = NotificationLog(
        source_service=source_service,
        target_type=target_type,
        target_id=target_id,
        title=title,
        body=body,
        data=json.dumps(data) if data else None,
        category=category,
        token_count=len(push_tokens),
        success_count=success_count,
        failure_count=failure_count,
        delivery_status=delivery_status,
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)

    logger.info(
        "Notification sent: %s -> %s:%s [%s] (%d/%d)",
        source_service, target_type, target_id,
        delivery_status, success_count, len(push_tokens),
    )
    return log_entry


async def _get_relay_jwt(
    relay_url: str,
    household_id: str,
    *,
    force_refresh: bool = False,
) -> str | None:
    """Resolve a household JWT for the relay.

    Lookup order:
    1. ``RELAY_HOUSEHOLD_JWT`` env override — operator escape hatch.
    2. In-memory cache for this ``household_id`` (populated by /v1/register).
    3. POST to ``{relay_url}/v1/register`` to mint a fresh one and cache it.

    Returns ``None`` if the relay can't be reached and we have no cached JWT.
    ``force_refresh=True`` skips the env override + cache (used after a 401,
    which signals the cached/configured token is no longer valid).
    """
    if not force_refresh:
        env_jwt = os.getenv("RELAY_HOUSEHOLD_JWT")
        if env_jwt:
            return env_jwt
        cached = _relay_jwt_cache.get(household_id)
        if cached:
            return cached

    global _relay_jwt_lock
    if _relay_jwt_lock is None:
        _relay_jwt_lock = asyncio.Lock()
    async with _relay_jwt_lock:
        if not force_refresh:
            cached = _relay_jwt_cache.get(household_id)
            if cached:
                return cached
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{relay_url.rstrip('/')}/v1/register",
                    json={"household_id": household_id},
                )
                resp.raise_for_status()
                token = resp.json()["jwt"]
                _relay_jwt_cache[household_id] = token
                logger.info("Registered with relay for household %s", household_id)
                return token
        except Exception as exc:  # noqa: BLE001 — any failure here means no JWT
            logger.error("Failed to register with relay for household %s: %s", household_id, exc)
            return None


async def _post_to_relay_send(
    relay_url: str,
    relay_jwt: str,
    household_id: str,
    payload: dict,
) -> httpx.Response:
    """Single POST to the relay's /v1/send. Caller handles status interpretation."""
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.post(
            f"{relay_url.rstrip('/')}/v1/send",
            json=payload,
            headers={
                "Authorization": f"Bearer {relay_jwt}",
                "X-Household-Id": household_id,
            },
        )


async def _deliver_via_relay(
    tokens: list[str],
    title: str,
    body: str,
    data: dict | None,
    priority: str,
    household_id: str,
) -> list[dict]:
    """Forward notification to centralized relay for Expo Push delivery.

    JWT is resolved lazily via :func:`_get_relay_jwt` — self-hosters never
    need to populate ``RELAY_HOUSEHOLD_JWT`` themselves; on first push the
    service registers with the relay and caches the minted token.
    """
    relay_url = os.getenv("RELAY_URL")

    if not relay_url:
        logger.info("No RELAY_URL configured, push delivery skipped")
        return [{"status": "skipped", "token": t} for t in tokens]

    relay_jwt = await _get_relay_jwt(relay_url, household_id)
    if not relay_jwt:
        logger.error(
            "No relay JWT available for household %s; push skipped", household_id,
        )
        return [{"status": "skipped", "token": t} for t in tokens]

    payload = {
        "tokens": tokens,
        "title": title,
        "body": body,
        "data": data or {},
        "priority": priority,
    }

    try:
        resp = await _post_to_relay_send(relay_url, relay_jwt, household_id, payload)
        if resp.status_code == 401:
            # Cached/configured JWT is stale (relay rotated its secret, etc.).
            # Force-refresh and try once more before giving up.
            logger.warning("Relay returned 401; refreshing JWT for household %s", household_id)
            relay_jwt = await _get_relay_jwt(relay_url, household_id, force_refresh=True)
            if not relay_jwt:
                return [{"status": "error", "error": "relay_http_401", "token": t} for t in tokens]
            resp = await _post_to_relay_send(relay_url, relay_jwt, household_id, payload)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        # Attach token to each result if not already present
        for i, result in enumerate(results):
            if "token" not in result and i < len(tokens):
                result["token"] = tokens[i]
        return results
    except httpx.HTTPStatusError as exc:
        logger.error("Relay returned %s: %s", exc.response.status_code, exc.response.text)
        # Queue for retry on transient errors
        if exc.response.status_code >= 500:
            await _queue_retry(RetryItem(
                tokens=tokens, title=title, body=body,
                data=data, priority=priority, household_id=household_id,
            ))
        return [{"status": "error", "error": f"relay_http_{exc.response.status_code}", "token": t} for t in tokens]
    except httpx.RequestError as exc:
        logger.error("Relay request failed: %s", exc)
        await _queue_retry(RetryItem(
            tokens=tokens, title=title, body=body,
            data=data, priority=priority, household_id=household_id,
        ))
        return [{"status": "error", "error": "relay_unreachable", "token": t} for t in tokens]


async def _queue_retry(item: RetryItem) -> None:
    """Queue a failed delivery for retry."""
    global _retry_queue
    if _retry_queue is None:
        _retry_queue = asyncio.Queue()
    if item.attempt < MAX_RETRIES:
        item.attempt += 1
        await _retry_queue.put(item)
        logger.info("Queued retry %d/%d for %d tokens", item.attempt, MAX_RETRIES, len(item.tokens))


async def process_retry_queue() -> None:
    """Background task to process retry queue with exponential backoff."""
    global _retry_queue
    if _retry_queue is None:
        _retry_queue = asyncio.Queue()

    while True:
        try:
            item: RetryItem = await _retry_queue.get()
            delay = RETRY_DELAYS[min(item.attempt - 1, len(RETRY_DELAYS) - 1)]
            logger.info("Retrying delivery in %ds (attempt %d/%d)", delay, item.attempt, MAX_RETRIES)
            await asyncio.sleep(delay)

            results = await _deliver_via_relay(
                tokens=item.tokens,
                title=item.title,
                body=item.body,
                data=item.data,
                priority=item.priority,
                household_id=item.household_id,
            )

            success = sum(1 for r in results if r.get("status") == "ok")
            logger.info("Retry result: %d/%d succeeded", success, len(item.tokens))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Retry processing error: %s", e)
