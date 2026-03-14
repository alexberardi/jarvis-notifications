"""Tests for notification service logic (dedup, relay forwarding, error handling)."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from app.services.notification_service import (
    _dedup_key,
    _is_duplicate,
    send_notification,
)


def test_dedup_key_deterministic():
    """Same inputs produce same key."""
    key1 = _dedup_key("service-a", "42", "Hello", "World", "alert")
    key2 = _dedup_key("service-a", "42", "Hello", "World", "alert")
    assert key1 == key2


def test_dedup_key_varies_by_category():
    """Different category produces different key."""
    key1 = _dedup_key("service-a", "42", "Hello", "World", "alert")
    key2 = _dedup_key("service-a", "42", "Hello", "World", "research")
    assert key1 != key2


def test_dedup_key_none_category():
    """None category produces consistent key."""
    key1 = _dedup_key("service-a", "42", "Hello", "World", None)
    key2 = _dedup_key("service-a", "42", "Hello", "World", None)
    assert key1 == key2


def test_is_duplicate_first_time():
    """First call is not a duplicate."""
    assert _is_duplicate("test-key-1") is False


def test_is_duplicate_second_time():
    """Second call within window is a duplicate."""
    _is_duplicate("test-key-2")
    assert _is_duplicate("test-key-2") is True


def test_is_duplicate_different_keys():
    """Different keys are not duplicates."""
    _is_duplicate("key-a")
    assert _is_duplicate("key-b") is False


@pytest.mark.asyncio
async def test_send_notification_dedup(db_session):
    """Duplicate notification is suppressed."""
    # First send
    log1 = await send_notification(
        db_session,
        source_service="test-service",
        target_type="user",
        target_id="42",
        title="Hello",
        body="World",
        category="alert",
    )
    assert log1.delivery_status == "skipped"  # No tokens registered

    # Second send (duplicate)
    log2 = await send_notification(
        db_session,
        source_service="test-service",
        target_type="user",
        target_id="42",
        title="Hello",
        body="World",
        category="alert",
    )
    assert log2.delivery_status == "skipped"
    assert log2.token_count == 0


@pytest.mark.asyncio
async def test_send_notification_no_relay(db_session):
    """Without RELAY_URL, delivery is skipped gracefully."""
    # Ensure no relay is configured
    os.environ.pop("RELAY_URL", None)

    from app.services.token_service import register_token
    register_token(
        db_session,
        user_id=42,
        household_id="test-household",
        push_token="ExponentPushToken[test123]",
        device_type="ios",
    )

    log = await send_notification(
        db_session,
        source_service="test-service",
        target_type="user",
        target_id="42",
        title="Test",
        body="No relay",
    )
    assert log.delivery_status == "skipped"
    assert log.token_count == 1


@pytest.mark.asyncio
async def test_send_notification_relay_success(db_session):
    """Successful relay delivery."""
    from app.services.token_service import register_token
    register_token(
        db_session,
        user_id=42,
        household_id="test-household",
        push_token="ExponentPushToken[relay-test]",
        device_type="ios",
    )

    mock_results = [{"status": "ok", "token": "ExponentPushToken[relay-test]", "ticket_id": "xxx"}]

    with patch("app.services.notification_service._deliver_via_relay", new_callable=AsyncMock) as mock_relay:
        mock_relay.return_value = mock_results

        log = await send_notification(
            db_session,
            source_service="test-service",
            target_type="user",
            target_id="42",
            title="Test",
            body="Relay success",
        )
        assert log.delivery_status == "delivered"
        assert log.success_count == 1
        assert log.failure_count == 0


@pytest.mark.asyncio
async def test_send_notification_device_not_registered(db_session):
    """DeviceNotRegistered error deactivates the token."""
    from app.services.token_service import register_token
    token = register_token(
        db_session,
        user_id=42,
        household_id="test-household",
        push_token="ExponentPushToken[bad-token]",
        device_type="ios",
    )
    assert token.is_active is True

    mock_results = [{"status": "error", "error": "DeviceNotRegistered", "token": "ExponentPushToken[bad-token]"}]

    with patch("app.services.notification_service._deliver_via_relay", new_callable=AsyncMock) as mock_relay:
        mock_relay.return_value = mock_results

        log = await send_notification(
            db_session,
            source_service="test-service",
            target_type="user",
            target_id="42",
            title="Test",
            body="Bad token",
        )
        assert log.delivery_status == "failed"
        assert log.failure_count == 1

    # Verify token was deactivated
    db_session.refresh(token)
    assert token.is_active is False


@pytest.mark.asyncio
async def test_send_notification_partial_delivery(db_session):
    """Mixed success/failure produces partial status."""
    from app.services.token_service import register_token
    register_token(
        db_session, user_id=42, household_id="test-hh",
        push_token="ExponentPushToken[good]", device_type="ios",
    )
    register_token(
        db_session, user_id=42, household_id="test-hh",
        push_token="ExponentPushToken[bad]", device_type="android",
    )

    mock_results = [
        {"status": "ok", "token": "ExponentPushToken[good]", "ticket_id": "t1"},
        {"status": "error", "error": "DeviceNotRegistered", "token": "ExponentPushToken[bad]"},
    ]

    with patch("app.services.notification_service._deliver_via_relay", new_callable=AsyncMock) as mock_relay:
        mock_relay.return_value = mock_results

        log = await send_notification(
            db_session,
            source_service="test-service",
            target_type="user",
            target_id="42",
            title="Partial",
            body="Partial delivery",
        )
        assert log.delivery_status == "partial"
        assert log.success_count == 1
        assert log.failure_count == 1
        assert log.token_count == 2


@pytest.mark.asyncio
async def test_send_notification_household_target(db_session):
    """Fan out to all devices in a household."""
    from app.services.token_service import register_token
    register_token(
        db_session, user_id=1, household_id="family-hh",
        push_token="ExponentPushToken[phone1]", device_type="ios",
    )
    register_token(
        db_session, user_id=2, household_id="family-hh",
        push_token="ExponentPushToken[phone2]", device_type="android",
    )

    mock_results = [
        {"status": "ok", "token": "ExponentPushToken[phone1]"},
        {"status": "ok", "token": "ExponentPushToken[phone2]"},
    ]

    with patch("app.services.notification_service._deliver_via_relay", new_callable=AsyncMock) as mock_relay:
        mock_relay.return_value = mock_results

        log = await send_notification(
            db_session,
            source_service="test-service",
            target_type="household",
            target_id="family-hh",
            title="Dinner",
            body="Dinner is ready!",
            category="recipe",
        )
        assert log.delivery_status == "delivered"
        assert log.token_count == 2
        assert log.success_count == 2


@pytest.mark.asyncio
async def test_send_notification_with_data_payload(db_session):
    """Notification with custom data payload is stored correctly."""
    log = await send_notification(
        db_session,
        source_service="test-service",
        target_type="user",
        target_id="99",
        title="Research",
        body="Your research is done",
        data={"type": "deep_research", "result_id": "abc-123"},
        priority="high",
        category="research",
    )
    assert log.data is not None
    import json
    data = json.loads(log.data)
    assert data["type"] == "deep_research"
    assert data["result_id"] == "abc-123"
