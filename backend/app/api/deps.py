from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User
from app.models.enums import AccountStatus, UserRole

# auto_error=False so a missing token returns our own error shape; also adds /docs "Authorize".
_bearer = HTTPBearer(auto_error=False)

_NOT_AUTHENTICATED = {"WWW-Authenticate": "Bearer"}


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """The user behind a valid Bearer token; 401 not_authenticated otherwise."""
    user_id = decode_access_token(credentials.credentials) if credentials else None
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise AppError(401, "not_authenticated", headers=_NOT_AUTHENTICATED)
    return user


_INACTIVE_CODES = {
    AccountStatus.PENDING: "account_pending",
    AccountStatus.DEACTIVATED: "account_deactivated",
}


def require_active_user(user: User = Depends(get_current_user)) -> User:
    """A user whose account is active; 403 account_pending or account_deactivated otherwise
    (a token outlives a later deactivation)."""
    if user.account_status in _INACTIVE_CODES:
        raise AppError(403, _INACTIVE_CODES[user.account_status])
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """An active coop_admin; 403 not_admin for anyone else."""
    if user.role != UserRole.COOP_ADMIN or user.account_status != AccountStatus.ACTIVE:
        raise AppError(403, "not_admin")
    return user
