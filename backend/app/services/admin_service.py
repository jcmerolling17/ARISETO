"""Cooperative administrator actions."""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.constants import DELETED_MOBILE_PATTERN
from app.core.errors import AppError
from app.core.security import now_ms
from app.models import Barangay, User
from app.models.enums import AccountStatus, UserRole
from app.schemas.admin import AdminUserItem, UserCounts

# Stored in place of the password hash of a processed account: not an Argon2 hash, so
# every password check against it fails, even if the account is reactivated later.
UNUSABLE_PASSWORD_HASH = "!deleted"
DELETED_FIRST_NAME = "Deleted"
DELETED_LAST_NAME = "Member"


def _processed():
    """SQL condition: the account's deletion request was processed (mobile D<user_id>)."""
    return User.mobile_no.op("~")(DELETED_MOBILE_PATTERN)


def is_processed(user: User) -> bool:
    return user.mobile_no == f"D{user.user_id}"


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def _search(q: str):
    """Case-insensitive search of the first and last name (also together), mobile number and
    member number. A search starting with 09 is also tried as +639 (the stored form)."""
    terms = [q]
    if q.startswith("09"):
        terms.append("+63" + q[1:])
    full_name = User.first_name + " " + User.last_name
    columns = (User.first_name, User.last_name, full_name, User.mobile_no, User.member_no)
    return or_(*(column.ilike(_like(term), escape="\\") for term in terms for column in columns))


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
    role: UserRole | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AdminUserItem]:
    """Accounts newest first (then the highest user_id), with optional filters.
    deletion_requested=true keeps requests not yet processed (as the counts do), false the
    accounts that never asked for deletion.
    """
    query = select(User, Barangay.barangay_name).outerjoin(
        Barangay, Barangay.barangay_id == User.barangay_id
    )
    if status is not None:
        query = query.where(User.account_status == status)
    if role is not None:
        query = query.where(User.role == role)
    if q and q.strip():
        query = query.where(_search(q.strip()))
    if deletion_requested is True:
        query = query.where(User.deletion_requested_at.is_not(None), ~_processed())
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


def counts(db: Session) -> UserCounts:
    """Member accounts (role member) in each account_status, and members with a deletion
    request not yet processed; the four cards on the Admin Approval List."""
    by_status = dict(
        db.execute(
            select(User.account_status, func.count())
            .where(User.role == UserRole.MEMBER)
            .group_by(User.account_status)
        ).all()
    )
    deletion_requested = db.scalar(
        select(func.count()).where(
            User.role == UserRole.MEMBER,
            User.deletion_requested_at.is_not(None),
            ~_processed(),
        )
    )
    return UserCounts(
        pending=by_status.get(AccountStatus.PENDING, 0),
        active=by_status.get(AccountStatus.ACTIVE, 0),
        deactivated=by_status.get(AccountStatus.DEACTIVATED, 0),
        deletion_requested=deletion_requested,
    )


def process_deletion(db: Session, admin: User, user_id: int) -> User:
    """Process a deletion request in one transaction: deactivate the account, end its
    sessions (as a password change does), rename it "Deleted Member", clear the email and
    barangay, replace the mobile and member numbers with values that can never log in or
    clash, and make the password unusable. Farm records stay. Processing again changes
    nothing.

    Errors (in this order): 404 user_not_found; 409 no_deletion_request,
    cannot_deactivate_self, last_active_admin.
    """
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        raise AppError(404, "user_not_found")
    if user.deletion_requested_at is None:
        db.rollback()
        raise AppError(409, "no_deletion_request")
    if is_processed(user):
        db.rollback()
        return user
    if user.user_id == admin.user_id:
        db.rollback()
        raise AppError(409, "cannot_deactivate_self")
    if user.role == UserRole.COOP_ADMIN and _is_last_active_admin(db, user):
        db.rollback()
        raise AppError(409, "last_active_admin")

    user.account_status = AccountStatus.DEACTIVATED
    user.password_changed_at = now_ms()
    user.password_hash = UNUSABLE_PASSWORD_HASH
    user.first_name = DELETED_FIRST_NAME
    user.last_name = DELETED_LAST_NAME
    user.email = None
    user.barangay_id = None
    # Sign-up and profile changes accept only +639 numbers and store member numbers in
    # capitals, so neither value can ever be entered by anyone.
    user.mobile_no = f"D{user.user_id}"
    user.member_no = f"deleted-{user.user_id}"
    db.commit()
    db.refresh(user)
    return user
