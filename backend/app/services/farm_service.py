"""Farm setup: register a farm and add its fields (Section 6 farms)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import PLANTING_WINDOW_YEARS
from app.core.errors import AppError
from app.models import (
    Barangay,
    CalendarTemplateTask,
    CropActivity,
    CropCycle,
    CropVariety,
    Farm,
    FarmAssignment,
    FarmField,
    User,
)
from app.models.enums import CropSeason, CycleStatus, FarmRole
from app.schemas.farm import CreatedField, FarmCreate, FarmCreated, FieldCreate, FieldCreated

_FIELD_NAME_INDEX = "uq_field_farm_id_lower_field_name"


def _years_from(day: date, years: int) -> date:
    """The same day `years` later (or earlier); Feb 29 becomes Feb 28 in a common year."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def planting_window(today: date) -> tuple[date, date]:
    """The first and last allowed sowing dates: within 2 years before or after today."""
    return _years_from(today, -PLANTING_WINDOW_YEARS), _years_from(today, PLANTING_WINDOW_YEARS)


def _check_planting_date(planting_date: date, today: date) -> None:
    first, last = planting_window(today)
    if not first <= planting_date <= last:
        raise AppError(422, "planting_date_out_of_range")


def _get_variety(db: Session, variety_id: int) -> CropVariety:
    variety = db.get(CropVariety, variety_id)
    if variety is None:
        raise AppError(422, "variety_not_found")
    return variety


def _open_cycle(
    db: Session,
    field: FarmField,
    variety: CropVariety,
    season: CropSeason,
    planting_date: date,
    today: date,
    target_yield_t_ha: Decimal | None = None,
) -> CropCycle:
    """Open a crop cycle over the whole field and schedule its calendar from the variety's
    template tasks."""
    cycle = CropCycle(
        field_id=field.field_id,
        variety_id=variety.variety_id,
        season=season,
        area_planted_ha=field.area_ha,
        planting_date=planting_date,
        expected_harvest_date=planting_date + timedelta(days=variety.maturity_days),
        target_yield_t_ha=target_yield_t_ha,
        status=CycleStatus.PLANNED if planting_date > today else CycleStatus.ACTIVE,
    )
    db.add(cycle)
    db.flush()

    template_tasks = db.scalars(
        select(CalendarTemplateTask)
        .where(CalendarTemplateTask.variety_id == variety.variety_id)
        .order_by(CalendarTemplateTask.week_no, CalendarTemplateTask.template_task_id)
    )
    db.add_all(
        CropActivity(
            cycle_id=cycle.cycle_id,
            template_task_id=task.template_task_id,
            title=task.task_name,
            scheduled_date=planting_date + timedelta(weeks=task.week_no),
            client_uuid=uuid.uuid4(),
        )
        for task in template_tasks
    )
    return cycle


def create_farm(db: Session, user: User, data: FarmCreate) -> FarmCreated:
    """Save the farm, its fields, each field's first crop cycle, and their calendars in one
    transaction, with the caller as owner. Any error leaves nothing saved."""
    if not data.fields:
        raise AppError(422, "no_fields")
    names = [item.field_name.lower() for item in data.fields]
    if len(set(names)) != len(names):
        raise AppError(422, "field_name_taken")
    barangay = db.get(Barangay, data.barangay_id)
    if barangay is None:
        raise AppError(422, "barangay_not_found")
    today = date.today()
    for item in data.fields:
        _check_planting_date(item.planting_date, today)
    varieties = {item.variety_id: _get_variety(db, item.variety_id) for item in data.fields}

    farm = Farm(
        farm_name=data.farm_name,
        barangay_id=barangay.barangay_id,
        latitude=barangay.center_latitude,
        longitude=barangay.center_longitude,
        total_area_ha=sum(item.area_ha for item in data.fields),
    )
    db.add(farm)
    db.flush()
    db.add(FarmAssignment(farm_id=farm.farm_id, user_id=user.user_id, role_on_farm=FarmRole.OWNER))

    created = []
    for item in data.fields:
        field = FarmField(farm_id=farm.farm_id, field_name=item.field_name, area_ha=item.area_ha)
        db.add(field)
        db.flush()
        cycle = _open_cycle(
            db, field, varieties[item.variety_id], data.season, item.planting_date, today
        )
        created.append(
            CreatedField(
                field_id=field.field_id,
                cycle_id=cycle.cycle_id,
                expected_harvest_date=cycle.expected_harvest_date,
            )
        )
    db.commit()
    return FarmCreated(farm_id=farm.farm_id, total_area_ha=farm.total_area_ha, fields=created)


def add_field(db: Session, user: User, farm_id: int, data: FieldCreate) -> FieldCreated:
    """Add a field to a farm the caller owns, open its first crop cycle, and update the
    farm's total area. The farm row is locked so two requests can't both pass the name
    check or miscount the total."""
    farm = db.get(Farm, farm_id, with_for_update=True)
    if farm is None:
        raise AppError(404, "farm_not_found")
    is_owner = db.scalar(
        select(FarmAssignment.assignment_id).where(
            FarmAssignment.farm_id == farm_id,
            FarmAssignment.user_id == user.user_id,
            FarmAssignment.role_on_farm == FarmRole.OWNER,
        )
    )
    if is_owner is None:
        raise AppError(403, "not_farm_owner")

    today = date.today()
    _check_planting_date(data.planting_date, today)
    variety = _get_variety(db, data.variety_id)

    name_taken = db.scalar(
        select(FarmField.field_id).where(
            FarmField.farm_id == farm_id,
            func.lower(FarmField.field_name) == data.field_name.lower(),
        )
    )
    if name_taken is not None:
        raise AppError(409, "field_name_taken")

    field = FarmField(farm_id=farm_id, field_name=data.field_name, area_ha=data.area_ha)
    db.add(field)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == _FIELD_NAME_INDEX:
            raise AppError(409, "field_name_taken") from exc
        raise
    cycle = _open_cycle(
        db, field, variety, data.season, data.planting_date, today, data.target_yield_t_ha
    )
    farm.total_area_ha = db.scalar(
        select(func.sum(FarmField.area_ha)).where(FarmField.farm_id == farm_id)
    )
    db.commit()

    return FieldCreated(
        field_id=field.field_id,
        cycle_id=cycle.cycle_id,
        expected_harvest_date=cycle.expected_harvest_date,
        total_area_ha=farm.total_area_ha,
    )
