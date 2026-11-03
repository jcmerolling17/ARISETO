"""Harvests (Section 6): the farm owner records each harvest of a crop cycle; a final harvest
closes the cycle as 'harvested'."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.seasons import philippine_today
from app.models import Crop, CropCycle, CropVariety, FarmField, HarvestRecord, User
from app.models.enums import CycleStatus, FarmRole
from app.schemas.harvest import HarvestCreate, HarvestCreated, HarvestItem
from app.services.expense_service import SeasonFilter, season_cycle_ids
from app.services.farm_service import farm_role_of

_CLOSED = (CycleStatus.HARVESTED, CycleStatus.FAILED)


def record_harvest(db: Session, user: User, cycle_id: int, data: HarvestCreate) -> HarvestCreated:
    """Save a harvest. The cycle row is locked until commit, so two final harvests can't both
    pass the closed check; with final_harvest the cycle becomes 'harvested' and gets its
    actual_harvest_date in the same transaction.

    Errors: 404 cycle_not_found (also when the caller is not a member of the cycle's farm);
    403 not_farm_owner; 409 cycle_closed; 422 harvest_date_out_of_range.
    """
    cycle = db.get(CropCycle, cycle_id, with_for_update=True)
    role = None
    if cycle is not None:
        farm_id = db.scalar(select(FarmField.farm_id).where(FarmField.field_id == cycle.field_id))
        role = farm_role_of(db, user, farm_id)
    if role is None:
        db.rollback()
        raise AppError(404, "cycle_not_found")
    if role != FarmRole.OWNER:
        db.rollback()
        raise AppError(403, "not_farm_owner")
    if cycle.status in _CLOSED:
        db.rollback()
        raise AppError(409, "cycle_closed")
    if not cycle.planting_date <= data.harvest_date <= philippine_today():
        db.rollback()
        raise AppError(422, "harvest_date_out_of_range")

    harvest = HarvestRecord(
        cycle_id=cycle_id,
        harvest_date=data.harvest_date,
        quantity_kg=data.quantity_kg,
        unit_price_php=data.unit_price_php,
    )
    db.add(harvest)
    if data.final_harvest:
        cycle.status = CycleStatus.HARVESTED
        cycle.actual_harvest_date = data.harvest_date
    db.commit()
    db.refresh(harvest)
    return HarvestCreated(
        harvest_id=harvest.harvest_id,
        gross_income_php=harvest.gross_income_php,
        cycle_status=cycle.status,
    )


def list_harvests(db: Session, where: SeasonFilter) -> list[HarvestItem]:
    """Harvests of the season's crop cycles (on the chosen field, if any), newest first."""
    cycle_ids = season_cycle_ids(db, where)
    if not cycle_ids:
        return []
    rows = db.execute(
        select(HarvestRecord, FarmField.field_name, Crop.crop_name)
        .join(CropCycle, CropCycle.cycle_id == HarvestRecord.cycle_id)
        .join(FarmField, FarmField.field_id == CropCycle.field_id)
        .join(CropVariety, CropVariety.variety_id == CropCycle.variety_id)
        .join(Crop, Crop.crop_id == CropVariety.crop_id)
        .where(HarvestRecord.cycle_id.in_(cycle_ids))
        .order_by(HarvestRecord.harvest_date.desc(), HarvestRecord.harvest_id.desc())
    )
    return [
        HarvestItem(
            harvest_id=harvest.harvest_id,
            cycle_id=harvest.cycle_id,
            field_name=field_name,
            crop_name=crop_name,
            harvest_date=harvest.harvest_date,
            quantity_kg=harvest.quantity_kg,
            unit_price_php=harvest.unit_price_php,
            gross_income_php=harvest.gross_income_php,
        )
        for harvest, field_name, crop_name in rows
    ]
