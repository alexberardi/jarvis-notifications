"""Tests for the self-scoped account purge endpoint (DELETE /api/v0/me/data)."""

from fastapi.testclient import TestClient

from app.db import get_db
from app.deps import get_current_user
from app.main import app
from app.models import DeviceToken, InboxItem
from app.services import account_service


HH = "test-household-123"
CALLER = 42  # matches conftest._mock_current_user
OTHER_USER = 99


def _make_token(db_session, *, user_id, push_token, household_id=HH):
    token = DeviceToken(
        user_id=user_id,
        household_id=household_id,
        push_token=push_token,
        device_type="ios",
        device_name="Test Device",
    )
    db_session.add(token)
    db_session.commit()
    db_session.refresh(token)
    return token


def _create_inbox(db_session, *, user_id, household_id=HH, title="Item"):
    item = InboxItem(
        user_id=user_id,
        household_id=household_id,
        title=title,
        summary="s",
        body="b",
        category="reminder",
        source_service="test",
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


# --- Service-layer tests ---

def test_purge_deletes_callers_tokens_and_inbox(db_session):
    _make_token(db_session, user_id=CALLER, push_token="tok-caller-1")
    _make_token(db_session, user_id=CALLER, push_token="tok-caller-2")
    _create_inbox(db_session, user_id=CALLER, title="mine-1")
    _create_inbox(db_session, user_id=CALLER, title="mine-2")

    result = account_service.purge_user_data(db_session, user_id=CALLER)

    assert result == {"device_tokens": 2, "inbox_items": 2}
    assert (
        db_session.query(DeviceToken)
        .filter(DeviceToken.user_id == CALLER)
        .count()
        == 0
    )
    assert (
        db_session.query(InboxItem).filter(InboxItem.user_id == CALLER).count() == 0
    )


def test_purge_leaves_other_users_rows_untouched(db_session):
    _make_token(db_session, user_id=CALLER, push_token="tok-caller")
    _make_token(db_session, user_id=OTHER_USER, push_token="tok-other")
    _create_inbox(db_session, user_id=CALLER, title="mine")
    _create_inbox(db_session, user_id=OTHER_USER, title="theirs")
    # Household-wide inbox item (user_id=None) must survive too.
    _create_inbox(db_session, user_id=None, title="shared")

    account_service.purge_user_data(db_session, user_id=CALLER)

    assert (
        db_session.query(DeviceToken)
        .filter(DeviceToken.user_id == OTHER_USER)
        .count()
        == 1
    )
    assert (
        db_session.query(InboxItem)
        .filter(InboxItem.user_id == OTHER_USER)
        .count()
        == 1
    )
    assert (
        db_session.query(InboxItem).filter(InboxItem.user_id.is_(None)).count() == 1
    )


def test_purge_is_idempotent_with_no_rows(db_session):
    result = account_service.purge_user_data(db_session, user_id=CALLER)
    assert result == {"device_tokens": 0, "inbox_items": 0}


# --- HTTP-layer tests ---

def test_purge_endpoint_returns_204_and_deletes(client, db_session):
    _make_token(db_session, user_id=CALLER, push_token="tok-http")
    _create_inbox(db_session, user_id=CALLER, title="http-item")

    res = client.request("DELETE", "/api/v0/me/data")
    assert res.status_code == 204
    assert res.content == b""

    assert (
        db_session.query(DeviceToken)
        .filter(DeviceToken.user_id == CALLER)
        .count()
        == 0
    )
    assert (
        db_session.query(InboxItem).filter(InboxItem.user_id == CALLER).count() == 0
    )


def test_purge_endpoint_only_affects_caller(client, db_session):
    _make_token(db_session, user_id=CALLER, push_token="tok-caller")
    _make_token(db_session, user_id=OTHER_USER, push_token="tok-other")
    _create_inbox(db_session, user_id=OTHER_USER, title="theirs")

    res = client.request("DELETE", "/api/v0/me/data")
    assert res.status_code == 204

    assert (
        db_session.query(DeviceToken)
        .filter(DeviceToken.user_id == OTHER_USER)
        .count()
        == 1
    )
    assert (
        db_session.query(InboxItem)
        .filter(InboxItem.user_id == OTHER_USER)
        .count()
        == 1
    )


def test_purge_endpoint_idempotent_over_http(client):
    # No rows seeded — endpoint still succeeds.
    first = client.request("DELETE", "/api/v0/me/data")
    second = client.request("DELETE", "/api/v0/me/data")
    assert first.status_code == 204
    assert second.status_code == 204


def test_purge_endpoint_requires_valid_jwt(db_session):
    """Without the get_current_user override, a missing/invalid JWT is rejected."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    # Only override the DB — leave real get_current_user in place so the JWT
    # validator runs.
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            # No Authorization header at all.
            no_header = unauth_client.request("DELETE", "/api/v0/me/data")
            assert no_header.status_code in (401, 403)

            # Present but garbage token.
            bad_token = unauth_client.request(
                "DELETE",
                "/api/v0/me/data",
                headers={"Authorization": "Bearer not-a-real-jwt"},
            )
            assert bad_token.status_code == 401
    finally:
        app.dependency_overrides.clear()
