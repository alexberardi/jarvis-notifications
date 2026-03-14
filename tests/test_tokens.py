"""Tests for token registration endpoints."""


def test_register_token(client, sample_token_data):
    """Register a push token."""
    resp = client.post("/api/v0/tokens", json=sample_token_data)
    assert resp.status_code == 200
    data = resp.json()
    assert data["push_token"] == sample_token_data["push_token"]
    assert data["device_type"] == "ios"
    assert data["device_name"] == "Alex's iPhone"
    assert data["is_active"] is True


def test_register_token_upsert(client, sample_token_data):
    """Re-registering same token updates rather than creates duplicate."""
    resp1 = client.post("/api/v0/tokens", json=sample_token_data)
    assert resp1.status_code == 200
    id1 = resp1.json()["id"]

    # Register again with same push_token
    resp2 = client.post("/api/v0/tokens", json=sample_token_data)
    assert resp2.status_code == 200
    id2 = resp2.json()["id"]

    assert id1 == id2  # Same record, updated


def test_register_token_invalid_device_type(client):
    """Reject invalid device_type."""
    resp = client.post("/api/v0/tokens", json={
        "push_token": "ExponentPushToken[xxx]",
        "device_type": "windows",
    })
    assert resp.status_code == 400
    assert "device_type" in resp.json()["detail"]


def test_unregister_token(client, sample_token_data):
    """Unregister a push token."""
    client.post("/api/v0/tokens", json=sample_token_data)

    resp = client.request("DELETE", "/api/v0/tokens", json={
        "push_token": sample_token_data["push_token"],
    })
    assert resp.status_code == 200

    # Verify it's deactivated
    resp = client.get("/api/v0/tokens/me")
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_unregister_nonexistent_token(client):
    """Unregistering a token that doesn't exist returns 404."""
    resp = client.request("DELETE", "/api/v0/tokens", json={
        "push_token": "ExponentPushToken[doesnotexist]",
    })
    assert resp.status_code == 404


def test_list_my_tokens(client, sample_token_data, another_token_data):
    """List active tokens for authenticated user."""
    client.post("/api/v0/tokens", json=sample_token_data)
    client.post("/api/v0/tokens", json=another_token_data)

    resp = client.get("/api/v0/tokens/me")
    assert resp.status_code == 200
    tokens = resp.json()
    assert len(tokens) == 2
    push_tokens = {t["push_token"] for t in tokens}
    assert sample_token_data["push_token"] in push_tokens
    assert another_token_data["push_token"] in push_tokens


def test_list_my_tokens_excludes_inactive(client, sample_token_data):
    """Inactive tokens are not returned."""
    client.post("/api/v0/tokens", json=sample_token_data)
    client.request("DELETE", "/api/v0/tokens", json={
        "push_token": sample_token_data["push_token"],
    })

    resp = client.get("/api/v0/tokens/me")
    assert resp.status_code == 200
    assert len(resp.json()) == 0
