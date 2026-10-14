from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import User
from app.schemas.admin import UserStatusResponse, UserStatusUpdate
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.patch("/users/{user_id}/status", response_model=UserStatusResponse)
def update_user_status(
    user_id: int,
    data: UserStatusUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserStatusResponse:
    """Approve a pending account ('active') or deactivate one. Cooperative administrators only.

    Errors: 401 not_authenticated; 403 not_admin; 404 user_not_found.
    """
    user = admin_service.set_account_status(db, user_id, data.account_status)
    return UserStatusResponse(user_id=user.user_id, account_status=user.account_status)
