"""The caller's in-app notifications (Section 6). A member only ever sees their own; someone
else's notification is 404 notification_not_found, so IDs are never revealed."""

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Notification, User
from app.models.enums import NotificationType
from app.schemas.notification import (
    NotificationItem,
    NotificationList,
    NotificationRead,
    ReadAllResult,
)


def list_notifications(
    db: Session,
    user: User,
    *,
    unread_only: bool = False,
    type: NotificationType | None = None,
    limit: int = 20,
    offset: int = 0,
) -> NotificationList:
    """Newest first (then the highest ID). unread_count ignores the filters."""
    query = select(Notification).where(Notification.user_id == user.user_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if type is not None:
        query = query.where(Notification.type == type)
    rows = db.scalars(
        query.order_by(Notification.created_at.desc(), Notification.notification_id.desc())
        .limit(limit)
        .offset(offset)
    )
    unread = db.scalar(
        select(func.count()).where(
            Notification.user_id == user.user_id, Notification.read_at.is_(None)
        )
    )
    return NotificationList(
        unread_count=unread, items=[NotificationItem.model_validate(row) for row in rows]
    )


def mark_read(
    db: Session, user: User, notification_id: int, now: datetime | None = None
) -> NotificationRead:
    """Set read_at once; marking it again keeps the first time."""
    notification = db.scalar(
        select(Notification)
        .where(
            Notification.notification_id == notification_id,
            Notification.user_id == user.user_id,
        )
        .with_for_update()
    )
    if notification is None:
        raise AppError(404, "notification_not_found")
    if notification.read_at is None:
        notification.read_at = now or datetime.now(UTC)
        db.commit()
    return NotificationRead(
        notification_id=notification.notification_id, read_at=notification.read_at
    )


def mark_all_read(db: Session, user: User, now: datetime | None = None) -> ReadAllResult:
    """Mark every unread notification of the caller read; returns how many changed."""
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == user.user_id, Notification.read_at.is_(None))
        .values(read_at=now or datetime.now(UTC))
    )
    db.commit()
    return ReadAllResult(updated=result.rowcount)
