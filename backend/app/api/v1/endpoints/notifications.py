from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.db.session import get_db
from app.models import User
from app.models.enums import NotificationType
from app.schemas.notification import NotificationList, NotificationRead, ReadAllResult
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
def list_notifications(
    unread_only: bool = False,
    type: NotificationType | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> NotificationList:
    """The caller's own notifications, newest first, with the count of all unread ones."""
    return notification_service.list_notifications(
        db, user, unread_only=unread_only, type=type, limit=limit, offset=offset
    )


@router.post("/read-all", response_model=ReadAllResult)
def mark_all_read(
    user: User = Depends(require_active_user), db: Session = Depends(get_db)
) -> ReadAllResult:
    """Mark all of the caller's unread notifications read."""
    return notification_service.mark_all_read(db, user)


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: int,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> NotificationRead:
    """Mark one of the caller's notifications read; the first read_at is kept.

    Errors: 404 notification_not_found, also for someone else's notification.
    """
    return notification_service.mark_read(db, user, notification_id)
