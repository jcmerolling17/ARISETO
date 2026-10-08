"""Registration, login, and admin-account creation (Section 4 USER rules, Section 6 auth)."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Barangay, User
from app.models.enums import AccountStatus, LanguageCode, UserRole
from app.schemas.auth import LoginRequest, LoginResponse, LoginUser, RegisterRequest

# Unique constraint -> 409 error code (Section 6).
_CONFLICT_CODES = {
    "uq_users_mobile_no": "mobile_taken",
    "uq_users_email": "email_taken",
    "uq_users_member_no": "member_no_taken",
}

_STATUS_ERRORS = {
    AccountStatus.PENDING: "account_pending",
    AccountStatus.DEACTIVATED: "account_deactivated",
}


def _ensure_unique(
    db: Session, *, mobile_no: str, email: str | None, member_no: str | None
) -> None:
    checks = (
        (User.mobile_no, mobile_no, "mobile_taken"),
        (User.email, email, "email_taken"),
        (User.member_no, member_no, "member_no_taken"),
    )
    for column, value, code in checks:
        if value is not None and db.scalar(select(User.user_id).where(column == value)):
            raise AppError(409, code)


def _save_user(db: Session, user: User) -> User:
    """Insert, turning a unique-constraint race into the matching 409 code."""
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint in _CONFLICT_CODES:
            raise AppError(409, _CONFLICT_CODES[constraint]) from exc
        raise
    db.refresh(user)
    return user


def register_member(db: Session, data: RegisterRequest) -> User:
    """Create a 'member' account in 'pending' status until a coop_admin approves it."""
    if data.barangay_id is not None:
        barangay = db.get(Barangay, data.barangay_id)
        if barangay is None or barangay.municipality != data.municipality:
            raise AppError(422, "barangay_municipality_mismatch")

    _ensure_unique(db, mobile_no=data.mobile_no, email=data.email, member_no=data.member_no)

    user = User(
        member_no=data.member_no,
        first_name=data.first_name,
        last_name=data.last_name,
        mobile_no=data.mobile_no,
        email=data.email,
        password_hash=hash_password(data.password),
        role=UserRole.MEMBER,
        barangay_id=data.barangay_id,
        municipality=data.municipality,
        preferred_language=data.preferred_language,
        account_status=AccountStatus.PENDING,
    )
    return _save_user(db, user)


def login(db: Session, data: LoginRequest) -> LoginResponse:
    """Check credentials first, then account status, so status never leaks for wrong passwords."""
    if data.mobile_no is not None:
        user = db.scalar(select(User).where(User.mobile_no == data.mobile_no))
    else:
        user = db.scalar(select(User).where(User.email == data.email))

    if not verify_password(data.password, user.password_hash if user else None):
        raise AppError(401, "invalid_credentials")
    if user.account_status in _STATUS_ERRORS:
        raise AppError(403, _STATUS_ERRORS[user.account_status])

    return LoginResponse(
        access_token=create_access_token(user.user_id, user.role.value),
        user=LoginUser(user_id=user.user_id, first_name=user.first_name, role=user.role),
    )


def create_admin(
    db: Session,
    *,
    first_name: str,
    last_name: str,
    mobile_no: str,
    password: str,
    municipality: str,
    email: str | None = None,
) -> User:
    """Create an active coop_admin account (used by the create-admin command)."""
    _ensure_unique(db, mobile_no=mobile_no, email=email, member_no=None)
    user = User(
        first_name=first_name,
        last_name=last_name,
        mobile_no=mobile_no,
        email=email,
        password_hash=hash_password(password),
        role=UserRole.COOP_ADMIN,
        municipality=municipality,
        preferred_language=LanguageCode.FIL,
        account_status=AccountStatus.ACTIVE,
    )
    return _save_user(db, user)
