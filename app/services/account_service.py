"""Self-scoped account data purge.

Deletes all notification-service rows keyed to a single user_id. Used by the
account-deletion flow orchestrated by jarvis-auth (DELETE /auth/me forwards the
user token here as DELETE /api/v0/me/data).
"""

import logging

from sqlalchemy.orm import Session

from app.models import DeviceToken, InboxItem

logger = logging.getLogger(__name__)


def purge_user_data(db: Session, *, user_id: int) -> dict[str, int]:
    """Delete every device token and inbox item owned by ``user_id``.

    Idempotent: returns zero counts when the user has no rows. Counts are
    returned for logging/observability only — the endpoint responds 204 either
    way.
    """
    tokens_deleted = (
        db.query(DeviceToken)
        .filter(DeviceToken.user_id == user_id)
        .delete(synchronize_session=False)
    )
    inbox_deleted = (
        db.query(InboxItem)
        .filter(InboxItem.user_id == user_id)
        .delete(synchronize_session=False)
    )
    db.commit()

    logger.info(
        "Purged user data for user %s: %s device tokens, %s inbox items",
        user_id,
        tokens_deleted,
        inbox_deleted,
    )
    return {"device_tokens": tokens_deleted, "inbox_items": inbox_deleted}
