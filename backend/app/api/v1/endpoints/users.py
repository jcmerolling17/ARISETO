from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.db.session import get_db
from app.models import User
from app.schemas.user import (
    DeletionRequested,
    PasswordChange,
    PasswordChanged,
    UserMe,
    UserUpdate,
)
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserMe)
def get_me(user: User = Depends(require_active_user), db: Session = Depends(get_db)) -> UserMe:
    """The signed-in account's profile."""
    return user_service.get_me(db, user)


@router.patch("/me", response_model=UserMe)
def update_me(
    data: UserUpdate,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> UserMe:
    """Change any of first_name, last_name, email, mobile_no, preferred_language.

    Errors: 403 invalid_current_password; 409 mobile_taken, email_taken;
    422 current_password_required.
    """
    return user_service.update_me(db, user, data)


@router.post("/me/password", response_model=PasswordChanged)
def change_password(
    data: PasswordChange,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> PasswordChanged:
    """Change the password; returns a fresh token, and tokens issued earlier stop working.

    Errors: 403 invalid_current_password; 422 password_unchanged.
    """
    return user_service.change_password(db, user, data)


@router.post("/me/deletion-request", response_model=DeletionRequested)
def request_deletion(
    user: User = Depends(require_active_user), db: Session = Depends(get_db)
) -> DeletionRequested:
    """Ask a coop_admin to delete the account; asking again keeps the first time."""
    user = user_service.request_deletion(db, user)
    return DeletionRequested(deletion_requested_at=user.deletion_requested_at)
