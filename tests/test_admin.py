"""Tests for admin endpoints."""

from datetime import datetime

from app.models import DeviceToken, NotificationLog


def test_health(client):
    """Health endpoint returns ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_info(client):
    """Info endpoint returns service identity."""
    resp = client.get("/info")
    assert resp.status_code == 200
    assert resp.json()["service"] == "jarvis-notifications"


def test_stats_empty(client):
    """Stats with no data returns zeros."""
    resp = client.get("/api/v0/admin/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tokens"]["total"] == 0
    assert data["tokens"]["active"] == 0
    assert data["notifications_24h"]["total"] == 0


def test_stats_with_data(client, db_session, sample_token_data):
    """Stats returns correct counts."""
    # Register a token
    client.post("/api/v0/tokens", json=sample_token_data)

    # Create a notification log entry
    log = NotificationLog(
        source_service="test",
        target_type="user",
        target_id="42",
        title="Test",
        body="Test notification",
        token_count=1,
        success_count=1,
        failure_count=0,
        delivery_status="delivered",
        created_at=datetime.utcnow(),
    )
    db_session.add(log)
    db_session.commit()

    resp = client.get("/api/v0/admin/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tokens"]["total"] == 1
    assert data["tokens"]["active"] == 1
    assert data["notifications_24h"]["total"] == 1
    assert data["notifications_24h"]["by_status"]["delivered"] == 1


def test_force_cleanup(client):
    """Force cleanup endpoint runs without error."""
    resp = client.post("/api/v0/admin/cleanup")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "logs_pruned" in data
    assert "tokens_deactivated" in data


def test_stats_tokens_by_household(client, db_session):
    """Stats groups tokens by household."""
    # Add tokens from two households
    for i, hh in enumerate(["household-a", "household-b", "household-b"]):
        token = DeviceToken(
            user_id=i + 1,
            household_id=hh,
            push_token=f"ExponentPushToken[tok{i}]",
            device_type="ios",
            is_active=True,
        )
        db_session.add(token)
    db_session.commit()

    resp = client.get("/api/v0/admin/stats")
    data = resp.json()
    by_hh = {h["household_id"]: h["count"] for h in data["tokens"]["by_household"]}
    assert by_hh["household-a"] == 1
    assert by_hh["household-b"] == 2
