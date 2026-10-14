from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.db.session import get_db
from app.models import User
from app.schemas.farm import FarmCreate, FarmCreated, FieldCreate, FieldCreated
from app.services import farm_service

router = APIRouter(prefix="/farms", tags=["farms"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=FarmCreated)
def create_farm(
    data: FarmCreate,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> FarmCreated:
    """Save a farm with its fields, each field's first crop cycle, and their calendars in
    one transaction; the caller becomes the owner.

    Errors: 401 not_authenticated; 403 account_pending | account_deactivated;
    422 no_fields | field_name_taken | barangay_not_found | planting_date_out_of_range |
    variety_not_found.
    """
    return farm_service.create_farm(db, user, data)


@router.post("/{farm_id}/fields", status_code=status.HTTP_201_CREATED, response_model=FieldCreated)
def add_field(
    farm_id: int,
    data: FieldCreate,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> FieldCreated:
    """Add a field to a farm and open its first crop cycle. Farm owners only.

    Errors: 401 not_authenticated; 403 account_pending | account_deactivated | not_farm_owner;
    404 farm_not_found; 409 field_name_taken;
    422 planting_date_out_of_range | variety_not_found.
    """
    return farm_service.add_field(db, user, farm_id, data)
