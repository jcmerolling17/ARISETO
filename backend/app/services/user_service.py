"""The signed-in account's own settings: profile, password, and deletion request (Section 6)."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, now_ms, verify_password
from app.models import Barangay, User
from app.schemas.user import PasswordChange, PasswordChanged, UserMe, UserUpdate
from app.services.auth_service import ensure_unique, save_user

# Login IDs: changing either needs the current password.
_LOGIN_FIELDS = ("mobile_no", "email")


def get_me(db: Session, user: User) -> UserMe:
    barangay = db.get(Barangay, user.barangay_id) if user.barangay_id is not None else None
    return UserMe(
        user_id=user.user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        mobile_no=user.mobile_no,
        email=user.email,
        member_no=user.member_no,
        municipality=user.municipality,
        barangay_id=user.barangay_id,
        barangay_name=barangay.barangay_name if barangay else None,
        preferred_language=user.preferred_language,
        role=user.role,
        account_status=user.account_status,
        created_at=user.created_at,
        deletion_requested_at=user.deletion_requested_at,
    )


def update_me(db: Session, user: User, data: UserUpdate) -> UserMe:
    """Change the sent fields. A mobile_no or email that differs from the stored one needs
    current_password, checked before uniqueness so taken numbers are not revealed without it.

    Errors: 422 current_password_required; 403 invalid_current_password;
    409 mobile_taken, email_taken.
    """
    changes = {
        name: value for name, value in data.changes().items() if value != getattr(user, name)
    }

    if any(name in changes for name in _LOGIN_FIELDS):
        if data.current_password is None:
            raise AppError(422, "current_password_required")
        if not verify_password(data.current_password, user.password_hash):
            raise AppError(403, "invalid_current_password")
        ensure_unique(
            db,
            mobile_no=changes.get("mobile_no"),
            email=changes.get("email"),
            member_no=None,
            except_user_id=user.user_id,
        )

    for name, value in changes.items():
        setattr(user, name, value)
    if changes:
        save_user(db, user)
    return get_me(db, user)


def change_password(db: Session, user: User, data: PasswordChange) -> PasswordChanged:
    """Set a new password and end other sessions: tokens issued before password_changed_at are
    refused, and the token returned here is issued at that same moment.

    Errors: 403 invalid_current_password; 422 password_unchanged.
    """
    if not verify_password(data.current_password, user.password_hash):
        raise AppError(403, "invalid_current_password")
    if data.new_password == data.current_password:
        raise AppError(422, "password_unchanged")

    changed_at = now_ms()
    user.password_hash = hash_password(data.new_password)
    user.password_changed_at = changed_at
    db.commit()
    return PasswordChanged(
        access_token=create_access_token(user.user_id, user.role.value, issued_at=changed_at)
    )


def request_deletion(db: Session, user: User) -> User:
    """Record the first deletion request; asking again keeps the first time. A coop_admin
    processes it later by deactivating the account and removing personal details."""
    if user.deletion_requested_at is None:
        user.deletion_requested_at = func.now()
        db.commit()
        db.refresh(user)
    return user
