from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.db.session import get_db
from app.models import User
from app.models.enums import CropSeason
from app.schemas.farm import (
    FarmCreate,
    FarmCreated,
    FarmSummary,
    FieldCreate,
    FieldCreated,
    FieldSummary,
)
from app.schemas.report import FarmReport
from app.schemas.weather import FarmWeather
from app.services import farm_service, report_service, weather_fetch_service, weather_service

router = APIRouter(prefix="/farms", tags=["farms"])


@router.get("", response_model=list[FarmSummary])
def list_farms(
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> list[FarmSummary]:
    """Farms the caller owns or works on, oldest first; empty if none.

    Errors: 401 not_authenticated; 403 account_pending | account_deactivated.
    """
    return farm_service.list_farms(db, user)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=FarmCreated)
def create_farm(
    data: FarmCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> FarmCreated:
    """Save a farm with its fields, each field's first crop cycle, and their calendars in
    one transaction; the caller becomes the owner. After the response, the farm's weather
    is fetched in the background; a failed fetch never changes the response.

    Errors: 401 not_authenticated; 403 account_pending | account_deactivated;
    422 no_fields | field_name_taken | barangay_not_found | planting_date_out_of_range |
    variety_not_found.
    """
    created = farm_service.create_farm(db, user, data)
    background_tasks.add_task(weather_fetch_service.fetch_new_farm, created.farm_id)
    return created


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


@router.get("/{farm_id}/fields", response_model=list[FieldSummary])
def list_fields(
    farm_id: int,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> list[FieldSummary]:
    """The farm's fields, each with its latest planned or active crop cycle. Farm members only.

    Errors: 401 not_authenticated; 403 account_pending | account_deactivated | not_farm_member.
    """
    return farm_service.list_fields(db, user, farm_id)


@router.get("/{farm_id}/weather", response_model=FarmWeather)
def farm_weather(
    farm_id: int,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> FarmWeather:
    """Latest reading, upcoming forecast, and yesterday/today/tomorrow ranges from
    WEATHER_LOG; never fetched live. Before the first fetch, current is null and the lists
    are empty; alerts stay empty until alert rules have a source. Farm members only.

    Errors: 401 not_authenticated; 403 account_pending | account_deactivated | not_farm_member.
    """
    return weather_service.farm_weather(db, user, farm_id)


@router.get("/{farm_id}/report", response_model=FarmReport)
def farm_report(
    farm_id: int,
    season: CropSeason | None = None,
    season_year: int | None = Query(None, ge=1, le=9999),
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> FarmReport:
    """The farm owner's report for one season (DFD 7.5): one entry per crop cycle and the
    totals, which match GET /farms/{farm_id}/summary. Computed on request, never stored.

    Errors: 401 not_authenticated; 403 account_pending | account_deactivated,
    not_farm_member (also for a farm that does not exist), not_farm_owner;
    422 season_incomplete.
    """
    return report_service.farm_report(db, user, farm_id, season, season_year)
