from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.db.session import get_db
from app.models import User
from app.schemas.crop import CropOut
from app.services import crop_service

router = APIRouter(tags=["crops"])


@router.get("/crops", response_model=list[CropOut])
def list_crops(
    _user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> list[CropOut]:
    """Crops with their varieties, for the farm setup variety list.

    Errors: 401 not_authenticated; 403 account_pending | account_deactivated.
    """
    return crop_service.list_crops(db)
