"""Admin endpoints — protected by ADMIN_API_KEY."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import verify_admin_key
from app.services import token_service
from app.services.cleanup_service import cleanup_old_logs, cleanup_stale_tokens

router = APIRouter()


@router.get("/stats", dependencies=[Depends(verify_admin_key)])
def get_stats(db: Session = Depends(get_db)):
    """Service stats: token counts, recent send volume."""
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from app.models import NotificationLog

    total_tokens = token_service.count_tokens(db, active_only=False)
    active_tokens = token_service.count_tokens(db, active_only=True)
    tokens_by_household = token_service.count_tokens_by_household(db)

    # Recent notifications (last 24h)
    cutoff = datetime.utcnow() - timedelta(hours=24)
    recent_count = db.query(func.count(NotificationLog.id)).filter(
        NotificationLog.created_at >= cutoff
    ).scalar() or 0

    # Status breakdown (last 24h)
    status_counts = dict(
        db.query(
            NotificationLog.delivery_status,
            func.count(NotificationLog.id),
        )
        .filter(NotificationLog.created_at >= cutoff)
        .group_by(NotificationLog.delivery_status)
        .all()
    )

    return {
        "tokens": {
            "total": total_tokens,
            "active": active_tokens,
            "by_household": tokens_by_household,
        },
        "notifications_24h": {
            "total": recent_count,
            "by_status": status_counts,
        },
    }


@router.post("/cleanup", dependencies=[Depends(verify_admin_key)])
def force_cleanup(db: Session = Depends(get_db)):
    """Trigger token/log pruning manually."""
    logs_pruned = cleanup_old_logs(db=db)
    tokens_deactivated = cleanup_stale_tokens(db=db)
    return {"status": "ok", "logs_pruned": logs_pruned, "tokens_deactivated": tokens_deactivated}
