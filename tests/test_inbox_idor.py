"""Single-item inbox endpoints must be scoped to the requesting user, not just
the household.

Security finding (intra-household IDOR): list/bulk/unread already apply the
per-user predicate `(user_id == me) OR (user_id IS NULL)`, but the single-item
service functions (`get_item`, `mark_read`, `delete_item`) scoped by
`household_id` ONLY. So GET/PATCH/DELETE `/api/v0/inbox/{id}` let any household
member read, mark, or delete another member's PERSONAL item (e.g. a deep-research
result targeted to a specific user) just by learning its UUID.

Fix: thread the caller's user_id through the single-item path with the same
visibility predicate the list/bulk paths use.
"""
from app.services import inbox_service


HH = "test-household-123"          # matches conftest mocked user's household
USER = 42                          # matches conftest mocked user_id
OTHER_USER = 99


def _create(db_session, *, household_id=HH, user_id=None, is_read=False, title="Item"):
    item = inbox_service.create_item(
        db_session,
        household_id=household_id,
        title=title,
        summary="s",
        body="b",
        category="research",
        source_service="test",
        user_id=user_id,
    )
    if is_read:
        item.is_read = True
        db_session.commit()
    return item


# --- Service layer ---

def test_get_item_hides_other_users_personal_item(db_session):
    theirs = _create(db_session, user_id=OTHER_USER)
    # The victim's item is invisible to USER...
    assert inbox_service.get_item(db_session, theirs.id, HH, user_id=USER) is None
    # ...but visible to its owner.
    assert inbox_service.get_item(db_session, theirs.id, HH, user_id=OTHER_USER) is not None


def test_get_item_shows_own_and_shared_items(db_session):
    mine = _create(db_session, user_id=USER)
    shared = _create(db_session, user_id=None)
    assert inbox_service.get_item(db_session, mine.id, HH, user_id=USER) is not None
    assert inbox_service.get_item(db_session, shared.id, HH, user_id=USER) is not None


def test_delete_item_blocks_other_users_item(db_session):
    theirs = _create(db_session, user_id=OTHER_USER)
    assert inbox_service.delete_item(db_session, theirs.id, HH, user_id=USER) is False
    # Still present for its owner.
    assert inbox_service.get_item(db_session, theirs.id, HH, user_id=OTHER_USER) is not None


def test_mark_read_blocks_other_users_item(db_session):
    theirs = _create(db_session, user_id=OTHER_USER, is_read=False)
    assert inbox_service.mark_read(db_session, theirs.id, HH, user_id=USER) is None
    db_session.refresh(theirs)
    assert theirs.is_read is False


# --- HTTP layer (conftest mocks the caller as user_id=42) ---

def test_get_endpoint_404_for_other_users_item(client, db_session):
    theirs = _create(db_session, user_id=OTHER_USER)
    res = client.get(f"/api/v0/inbox/{theirs.id}")
    assert res.status_code == 404
    # And it was NOT auto-marked read as a side effect of the probe.
    db_session.refresh(theirs)
    assert theirs.is_read is False


def test_patch_read_endpoint_404_for_other_users_item(client, db_session):
    theirs = _create(db_session, user_id=OTHER_USER)
    res = client.patch(f"/api/v0/inbox/{theirs.id}/read")
    assert res.status_code == 404


def test_delete_endpoint_404_for_other_users_item(client, db_session):
    theirs = _create(db_session, user_id=OTHER_USER)
    res = client.delete(f"/api/v0/inbox/{theirs.id}")
    assert res.status_code == 404
    assert inbox_service.get_item(db_session, theirs.id, HH, user_id=OTHER_USER) is not None


def test_get_endpoint_200_for_own_item(client, db_session):
    mine = _create(db_session, user_id=USER)
    res = client.get(f"/api/v0/inbox/{mine.id}")
    assert res.status_code == 200
    assert res.json()["id"] == mine.id


def test_get_endpoint_200_for_shared_item(client, db_session):
    shared = _create(db_session, user_id=None)
    res = client.get(f"/api/v0/inbox/{shared.id}")
    assert res.status_code == 200
    assert res.json()["id"] == shared.id
