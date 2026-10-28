"""Cooperative administrator actions."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Barangay, User
from app.models.enums import AccountStatus, UserRole
from app.schemas.admin import AdminUserItem


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


def list_users(
    db: Session,
    *,
    status: AccountStatus | None = None,
    deletion_requested: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AdminUserItem]:
    """Accounts newest first (then the highest user_id), with optional filters.
    deletion_requested=true keeps accounts that asked for deletion, false those that did not.
    """
    query = select(User, Barangay.barangay_name).outerjoin(
        Barangay, Barangay.barangay_id == User.barangay_id
    )
    if status is not None:
        query = query.where(User.account_status == status)
    if deletion_requested is True:
        query = query.where(User.deletion_requested_at.is_not(None))
    elif deletion_requested is False:
        query = query.where(User.deletion_requested_at.is_(None))
    rows = db.execute(
        query.order_by(User.created_at.desc(), User.user_id.desc()).limit(limit).offset(offset)
    )
    return [
        AdminUserItem(
            user_id=user.user_id,
            first_name=user.first_name,
            last_name=user.last_name,
            mobile_no=user.mobile_no,
            email=user.email,
            member_no=user.member_no,
            municipality=user.municipality,
            barangay_name=barangay_name,
            role=user.role,
            account_status=user.account_status,
            created_at=user.created_at,
            deletion_requested_at=user.deletion_requested_at,
        )
        for user, barangay_name in rows
    ]


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
