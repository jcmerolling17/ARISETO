"""Cooperative administrator actions."""

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import User
from app.models.enums import AccountStatus


def set_account_status(db: Session, user_id: int, account_status: str) -> User:
    """Approve a pending account ('active') or deactivate an active one."""
    user = db.get(User, user_id)
    if user is None:
        raise AppError(404, "user_not_found")
    user.account_status = AccountStatus(account_status)
    db.commit()
    db.refresh(user)
    return user
