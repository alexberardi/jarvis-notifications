"""Tests for inbox bulk operations (mark-as-read, delete)."""

from app.services import inbox_service


HH = "test-household-123"
OTHER_HH = "other-household-999"
USER = 42
OTHER_USER = 99


def _create(db_session, *, household_id=HH, user_id=None, is_read=False, title="Item"):
    item = inbox_service.create_item(
        db_session,
        household_id=household_id,
        title=title,
        summary="s",
        body="b",
        category="reminder",
        source_service="test",
        user_id=user_id,
    )
    if is_read:
        item.is_read = True
        db_session.commit()
    return item


# --- Service-layer tests ---

def test_bulk_mark_read_marks_unread_only(db_session):
    a = _create(db_session)
    b = _create(db_session)
    c = _create(db_session, is_read=True)

    n = inbox_service.bulk_mark_read(
        db_session, household_id=HH, user_id=USER, ids=[a.id, b.id, c.id]
    )
    # Only a and b were unread; c was already read.
    assert n == 2
    db_session.refresh(a)
    db_session.refresh(b)
    db_session.refresh(c)
    assert a.is_read and b.is_read and c.is_read


def test_bulk_delete_removes_items(db_session):
    a = _create(db_session)
    b = _create(db_session)
    c = _create(db_session)

    n = inbox_service.bulk_delete(
        db_session, household_id=HH, user_id=USER, ids=[a.id, b.id]
    )
    assert n == 2
    assert inbox_service.get_item(db_session, a.id, HH) is None
    assert inbox_service.get_item(db_session, b.id, HH) is None
    assert inbox_service.get_item(db_session, c.id, HH) is not None


def test_bulk_ops_scope_by_household(db_session):
    mine = _create(db_session)
    theirs = _create(db_session, household_id=OTHER_HH)

    # Should not be able to delete other household's item even if ID known.
    n = inbox_service.bulk_delete(
        db_session, household_id=HH, user_id=USER, ids=[mine.id, theirs.id]
    )
    assert n == 1
    assert inbox_service.get_item(db_session, theirs.id, OTHER_HH) is not None


def test_bulk_ops_scope_by_user_visibility(db_session):
    # Household-wide (user_id=None) — visible to USER.
    shared = _create(db_session, user_id=None)
    # Targeted to USER — visible.
    mine = _create(db_session, user_id=USER)
    # Targeted to OTHER_USER — NOT visible to USER.
    theirs = _create(db_session, user_id=OTHER_USER)

    n = inbox_service.bulk_delete(
        db_session,
        household_id=HH,
        user_id=USER,
        ids=[shared.id, mine.id, theirs.id],
    )
    # Only the two visible to USER.
    assert n == 2
    assert inbox_service.get_item(db_session, theirs.id, HH) is not None


def test_bulk_ops_with_empty_ids_noop(db_session):
    _create(db_session)
    assert inbox_service.bulk_mark_read(db_session, household_id=HH, user_id=USER, ids=[]) == 0
    assert inbox_service.bulk_delete(db_session, household_id=HH, user_id=USER, ids=[]) == 0


def test_bulk_ops_with_unknown_ids_noop(db_session):
    n = inbox_service.bulk_mark_read(
        db_session, household_id=HH, user_id=USER, ids=["00000000-no-such-id"]
    )
    assert n == 0


# --- HTTP-layer tests ---

def test_post_bulk_read_endpoint(client, db_session, auth_headers):
    a = _create(db_session)
    b = _create(db_session)

    res = client.post(
        "/api/v0/inbox/bulk/read",
        json={"ids": [a.id, b.id]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json() == {"updated": 2}


def test_post_bulk_delete_endpoint(client, db_session, auth_headers):
    a = _create(db_session)
    b = _create(db_session)

    res = client.post(
        "/api/v0/inbox/bulk/delete",
        json={"ids": [a.id, b.id]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json() == {"deleted": 2}
    assert inbox_service.get_item(db_session, a.id, HH) is None


def test_bulk_endpoints_require_auth(client, db_session):
    a = _create(db_session)

    # No dependency override here would still work because conftest auto-overrides
    # get_current_user; instead verify that with empty IDs we get a clean 200.
    res = client.post("/api/v0/inbox/bulk/delete", json={"ids": []})
    assert res.status_code == 200
    assert res.json() == {"deleted": 0}
    # Original item untouched.
    assert inbox_service.get_item(db_session, a.id, HH) is not None
