"""Tests for notification sending endpoints."""

import pytest


def test_send_notification_no_tokens(client, sample_notification_data):
    """Send notification when no tokens are registered."""
    resp = client.post("/api/v0/notify", json=sample_notification_data)
    assert resp.status_code == 200
    data = resp.json()
    assert data["delivery_status"] == "skipped"
    assert data["token_count"] == 0


def test_send_notification_with_tokens(client, sample_token_data, sample_notification_data):
    """Send notification with registered tokens (relay not configured)."""
    # Register a token first
    client.post("/api/v0/tokens", json=sample_token_data)

    resp = client.post("/api/v0/notify", json=sample_notification_data)
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_count"] == 1
    assert data["delivery_status"] == "skipped"  # No relay configured


def test_send_notification_invalid_target_type(client):
    """Reject invalid target_type."""
    resp = client.post("/api/v0/notify", json={
        "target_type": "group",
        "target_id": "1",
        "title": "Test",
        "body": "Test body",
    })
    assert resp.status_code == 400
    assert "target_type" in resp.json()["detail"]


def test_send_notification_invalid_priority(client):
    """Reject invalid priority."""
    resp = client.post("/api/v0/notify", json={
        "target_type": "user",
        "target_id": "1",
        "title": "Test",
        "body": "Test body",
        "priority": "urgent",
    })
    assert resp.status_code == 400
    assert "priority" in resp.json()["detail"]


def test_send_to_household(client, sample_token_data):
    """Send notification to a household target."""
    client.post("/api/v0/tokens", json=sample_token_data)

    resp = client.post("/api/v0/notify", json={
        "target_type": "household",
        "target_id": "test-household-123",
        "title": "Dinner Ready",
        "body": "Come to the kitchen!",
        "category": "recipe",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_count"] == 1


def test_batch_notify(client, sample_token_data):
    """Send batch notifications."""
    client.post("/api/v0/tokens", json=sample_token_data)

    resp = client.post("/api/v0/notify/batch", json={
        "notifications": [
            {
                "target_type": "user",
                "target_id": "42",
                "title": "First",
                "body": "First notification",
            },
            {
                "target_type": "user",
                "target_id": "42",
                "title": "Second",
                "body": "Second notification",
            },
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


def test_batch_notify_too_many(client):
    """Reject batch with more than 100 notifications."""
    notifications = [
        {"target_type": "user", "target_id": "42", "title": f"N{i}", "body": f"Body {i}"}
        for i in range(101)
    ]
    resp = client.post("/api/v0/notify/batch", json={"notifications": notifications})
    assert resp.status_code == 400
    assert "100" in resp.json()["detail"]
