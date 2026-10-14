"""Cooperative administrator actions."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import User
from app.models.enums import AccountStatus, UserRole


def _is_last_active_admin(db: Session, user: User) -> bool:
    """True when no active coop_admin other than this user would remain.

    Locks the active coop_admin rows (in user_id order, so concurrent requests cannot
    deadlock) until commit: two admins deactivating each other at the same moment are
    handled one after the other, and the second one sees the first change.
    """
    active_admin_ids = db.scalars(
        select(User.user_id)
        .where(User.role == UserRole.COOP_ADMIN, User.account_status == AccountStatus.ACTIVE)
        .order_by(User.user_id)
        .with_for_update()
    ).all()
    return not any(admin_id != user.user_id for admin_id in active_admin_ids)


def set_account_status(db: Session, admin: User, user_id: int, account_status: str) -> User:
    """Approve a pending account ('active') or deactivate an active one (Section 6).

    Errors: 404 user_not_found; 409 cannot_deactivate_self, last_active_admin.
    """
    user = db.get(User, user_id)
    if user is None:
        raise AppError(404, "user_not_found")

    new_status = AccountStatus(account_status)
    if new_status == AccountStatus.DEACTIVATED:
        if user.user_id == admin.user_id:
            raise AppError(409, "cannot_deactivate_self")
        if user.role == UserRole.COOP_ADMIN and _is_last_active_admin(db, user):
            db.rollback()
            raise AppError(409, "last_active_admin")

    user.account_status = new_status
    db.commit()
    db.refresh(user)
    return user
