from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.db.session import get_db
from app.models import User
from app.schemas.farm import FarmCreate, FarmOut, FieldCreate, FieldOut
from app.services import farm_service

router = APIRouter(prefix="/farms", tags=["farms"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=FarmOut)
def create_farm(
    data: FarmCreate,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> FarmOut:
    """Register a farm; the caller becomes its owner.

    Errors: 401 not_authenticated; 403 account_pending | account_deactivated;
    422 barangay_not_found | coordinates_outside_province.
    """
    farm = farm_service.create_farm(db, user, data)
    return FarmOut.model_validate(farm)


@router.post("/{farm_id}/fields", status_code=status.HTTP_201_CREATED, response_model=FieldOut)
def add_field(
    farm_id: int,
    data: FieldCreate,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> FieldOut:
    """Add one field (plot) to a farm. Farm owners only.

    Errors: 401 not_authenticated; 403 account_pending | account_deactivated | not_farm_owner;
    404 farm_not_found; 409 field_name_taken;
    422 area_exceeds_farm | planting_date_out_of_range.
    """
    return farm_service.add_field(db, user, farm_id, data)
