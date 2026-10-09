"""Farm setup: register a farm and add its fields (Section 6 farms)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import PLANTING_WINDOW_DAYS, PROVINCE_BOUNDS
from app.core.errors import AppError
from app.models import Barangay, Crop, Farm, FarmAssignment, FarmField, User
from app.models.enums import FarmRole
from app.schemas.farm import FarmCreate, FieldCreate, FieldOut

_FIELD_NAME_INDEX = "uq_field_farm_id_lower_field_name"


def _inside_province(latitude: Decimal, longitude: Decimal) -> bool:
    bounds = PROVINCE_BOUNDS
    return (
        bounds["min_lat"] <= latitude <= bounds["max_lat"]
        and bounds["min_lon"] <= longitude <= bounds["max_lon"]
    )


def create_farm(db: Session, user: User, data: FarmCreate) -> Farm:
    """Create the farm and record the caller as its owner in FARM_ASSIGNMENT."""
    if db.get(Barangay, data.barangay_id) is None:
        raise AppError(422, "barangay_not_found")
    if not _inside_province(data.latitude, data.longitude):
        raise AppError(422, "coordinates_outside_province")

    farm = Farm(
        farm_name=data.farm_name,
        barangay_id=data.barangay_id,
        latitude=data.latitude,
        longitude=data.longitude,
        total_area_ha=data.total_area_ha,
    )
    db.add(farm)
    db.flush()
    db.add(FarmAssignment(farm_id=farm.farm_id, user_id=user.user_id, role_on_farm=FarmRole.OWNER))
    db.commit()
    db.refresh(farm)
    return farm


def add_field(db: Session, user: User, farm_id: int, data: FieldCreate) -> FieldOut:
    """Add one field to a farm the caller owns. The farm row is locked so two requests can't
    both pass the name and area checks."""
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

    if abs((data.planting_date - date.today()).days) > PLANTING_WINDOW_DAYS:
        raise AppError(422, "planting_date_out_of_range")

    name_taken = db.scalar(
        select(FarmField.field_id).where(
            FarmField.farm_id == farm_id,
            func.lower(FarmField.field_name) == data.field_name.lower(),
        )
    )
    if name_taken is not None:
        raise AppError(409, "field_name_taken")

    used_ha = db.scalar(
        select(func.coalesce(func.sum(FarmField.area_ha), 0)).where(FarmField.farm_id == farm_id)
    )
    if used_ha + data.area_ha > farm.total_area_ha:
        raise AppError(422, "area_exceeds_farm")

    crop = db.scalar(select(Crop).where(func.lower(Crop.crop_name) == data.crop))
    if crop is None:
        raise RuntimeError("The crop table is not seeded; run `alembic upgrade head`.")

    field = FarmField(
        farm_id=farm_id,
        field_name=data.field_name,
        crop_id=crop.crop_id,
        variety_name=data.variety,
        area_ha=data.area_ha,
        planting_date=data.planting_date,
        planting_method=data.planting_method,
        season=data.season,
    )
    db.add(field)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == _FIELD_NAME_INDEX:
            raise AppError(409, "field_name_taken") from exc
        raise
    db.refresh(field)

    return FieldOut(
        field_id=field.field_id,
        farm_id=field.farm_id,
        field_name=field.field_name,
        crop=crop.crop_name.lower(),
        variety=field.variety_name,
        area_ha=field.area_ha,
        planting_date=field.planting_date,
        planting_method=field.planting_method,
        season=field.season,
    )
