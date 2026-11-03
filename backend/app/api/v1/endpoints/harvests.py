from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.db.session import get_db
from app.models import User
from app.models.enums import CropSeason
from app.schemas.harvest import HarvestCreate, HarvestCreated, HarvestItem
from app.services import expense_service, harvest_service

router = APIRouter(tags=["harvests"])


@router.post(
    "/cycles/{cycle_id}/harvests",
    status_code=status.HTTP_201_CREATED,
    response_model=HarvestCreated,
)
def record_harvest(
    cycle_id: int,
    data: HarvestCreate,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HarvestCreated:
    """Record a harvest of a crop cycle; final_harvest true closes the cycle. Owner of the
    cycle's farm only.

    Errors: 403 not_farm_owner; 404 cycle_not_found; 409 cycle_closed;
    422 harvest_date_out_of_range.
    """
    return harvest_service.record_harvest(db, user, cycle_id, data)


@router.get("/farms/{farm_id}/harvests", response_model=list[HarvestItem])
def list_harvests(
    farm_id: int,
    season: CropSeason | None = None,
    season_year: int | None = Query(None, ge=1, le=9999),
    field_id: int | None = None,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> list[HarvestItem]:
    """A season's harvests, newest first. Farm members only.

    Errors: 403 not_farm_member; 422 season_incomplete, field_not_in_farm.
    """
    where = expense_service.resolve_filter(db, user, farm_id, season, season_year, field_id)
    return harvest_service.list_harvests(db, where)
