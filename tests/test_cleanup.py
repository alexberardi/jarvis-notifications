"""Tests for cleanup service."""

from datetime import datetime, timedelta

from app.models import DeviceToken, NotificationLog
from app.services.cleanup_service import cleanup_old_logs, cleanup_stale_tokens


def test_cleanup_old_logs(db_session):
    """Prune logs older than retention window."""
    # Create old log entry
    old_log = NotificationLog(
        source_service="test",
        target_type="user",
        target_id="1",
        title="Old",
        body="Old notification",
        token_count=1,
        success_count=1,
        failure_count=0,
        delivery_status="delivered",
        created_at=datetime.utcnow() - timedelta(days=31),
    )
    # Create recent log entry
    recent_log = NotificationLog(
        source_service="test",
        target_type="user",
        target_id="1",
        title="Recent",
        body="Recent notification",
        token_count=1,
        success_count=1,
        failure_count=0,
        delivery_status="delivered",
        created_at=datetime.utcnow(),
    )
    db_session.add_all([old_log, recent_log])
    db_session.commit()

    count = cleanup_old_logs(retention_days=30, db=db_session)
    assert count == 1

    # Recent log should remain
    remaining = db_session.query(NotificationLog).all()
    assert len(remaining) == 1
    assert remaining[0].title == "Recent"


def test_cleanup_old_logs_nothing_to_prune(db_session):
    """No logs to prune returns 0."""
    count = cleanup_old_logs(retention_days=30, db=db_session)
    assert count == 0


def test_cleanup_stale_tokens(db_session):
    """Deactivate tokens not used in 90+ days."""
    stale_token = DeviceToken(
        user_id=1,
        household_id="household-1",
        push_token="ExponentPushToken[stale]",
        device_type="ios",
        is_active=True,
        last_used_at=datetime.utcnow() - timedelta(days=91),
    )
    active_token = DeviceToken(
        user_id=1,
        household_id="household-1",
        push_token="ExponentPushToken[active]",
        device_type="ios",
        is_active=True,
        last_used_at=datetime.utcnow() - timedelta(days=1),
    )
    # Token with no last_used_at should NOT be deactivated
    new_token = DeviceToken(
        user_id=1,
        household_id="household-1",
        push_token="ExponentPushToken[new]",
        device_type="ios",
        is_active=True,
        last_used_at=None,
    )
    db_session.add_all([stale_token, active_token, new_token])
    db_session.commit()

    count = cleanup_stale_tokens(db=db_session)
    assert count == 1

    db_session.refresh(stale_token)
    db_session.refresh(active_token)
    db_session.refresh(new_token)

    assert stale_token.is_active is False
    assert active_token.is_active is True
    assert new_token.is_active is True


def test_cleanup_stale_tokens_none_stale(db_session):
    """No stale tokens returns 0."""
    count = cleanup_stale_tokens(db=db_session)
    assert count == 0
