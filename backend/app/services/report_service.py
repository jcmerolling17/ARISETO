"""Farm report (DFD 7.4 and 7.5) and cooperative report (DFD 7.6), computed on request from
the stored records and never saved.

A crop cycle belongs to a season by its recorded season and season year, the rule GET
/farms/{farm_id}/summary uses, so the farm report's totals always match the summary. The
cooperative report adds up the same per-farm figures; a scan belongs to the season of its
Philippine date and is placed by its cycle's farm, or by the member's municipality when no
field was chosen.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import MUNICIPALITIES
from app.core.errors import AppError
from app.core.seasons import philippine_midnight, philippine_today, season_dates, season_of
from app.models import (
    Barangay,
    Crop,
    CropActivity,
    CropCycle,
    CropVariety,
    Diagnosis,
    Disease,
    Expense,
    Farm,
    FarmField,
    HarvestRecord,
    User,
)
from app.models.enums import (
    AccountStatus,
    CropSeason,
    CycleStatus,
    FarmRole,
    ResultStatus,
    UserRole,
)
from app.schemas.report import (
    CooperativeReport,
    CropTotals,
    DiseaseCount,
    FarmReport,
    FieldReport,
    ReportTotals,
    ScanCounts,
)
from app.services import expense_service
from app.services.calendar_service import FINISHED, completion_pct
from app.services.farm_service import require_farm_member

_ZERO = Decimal(0)


@dataclass
class CycleFigures:
    """One crop cycle's figures for the season, shared by both reports."""

    cycle: CropCycle
    field_name: str
    crop_id: int
    crop_name: str
    variety_name: str
    expenses: Decimal = _ZERO
    harvest_kg: Decimal = _ZERO
    gross: Decimal = _ZERO
    has_harvest: bool = False
    tasks: int = 0
    finished_tasks: int = 0
    scans: Counter = field(default_factory=Counter)
    diseases: Counter = field(default_factory=Counter)


def _season(season: CropSeason | None, season_year: int | None) -> tuple[CropSeason, int]:
    """The chosen season, or the current one by today's Philippine date.

    Errors: 422 season_incomplete."""
    if (season is None) != (season_year is None):
        raise AppError(422, "season_incomplete")
    if season is None:
        return season_of(philippine_today())
    return season, season_year


def _yield_t_ha(harvest_kg: Decimal, area_ha: Decimal) -> float | None:
    if not area_ha:
        return None
    value = harvest_kg / 1000 / area_ha
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _top(diseases: Counter) -> list[tuple[str, int]]:
    """Most scans first, then name A to Z."""
    return sorted(diseases.items(), key=lambda item: (-item[1], item[0]))


def cycle_figures(
    db: Session, farm_id: int, season: CropSeason, season_year: int
) -> list[CycleFigures]:
    """The farm's crop cycles in the season, in field order and then by sowing date."""
    # season_cycle_ids is the summary's own season rule; the role is not used there.
    where = expense_service.SeasonFilter(farm_id, FarmRole.OWNER, season, season_year, None)
    cycle_ids = expense_service.season_cycle_ids(db, where)
    if not cycle_ids:
        return []

    rows = db.execute(
        select(CropCycle, FarmField.field_name, Crop.crop_id, Crop.crop_name, CropVariety)
        .join(FarmField, FarmField.field_id == CropCycle.field_id)
        .join(CropVariety, CropVariety.variety_id == CropCycle.variety_id)
        .join(Crop, Crop.crop_id == CropVariety.crop_id)
        .where(CropCycle.cycle_id.in_(cycle_ids))
        .order_by(FarmField.field_id, CropCycle.planting_date, CropCycle.cycle_id)
    ).all()
    figures = {
        cycle.cycle_id: CycleFigures(
            cycle=cycle,
            field_name=field_name,
            crop_id=crop_id,
            crop_name=crop_name,
            variety_name=variety.variety_name,
        )
        for cycle, field_name, crop_id, crop_name, variety in rows
    }

    for cycle_id, amount in db.execute(
        select(Expense.cycle_id, func.sum(Expense.amount_php))
        .where(Expense.cycle_id.in_(cycle_ids))
        .group_by(Expense.cycle_id)
    ):
        figures[cycle_id].expenses = amount
    for cycle_id, kg, gross in db.execute(
        select(
            HarvestRecord.cycle_id,
            func.sum(HarvestRecord.quantity_kg),
            func.sum(HarvestRecord.gross_income_php),
        )
        .where(HarvestRecord.cycle_id.in_(cycle_ids))
        .group_by(HarvestRecord.cycle_id)
    ):
        figures[cycle_id].harvest_kg, figures[cycle_id].gross = kg, gross
        figures[cycle_id].has_harvest = True
    for cycle_id, total, finished in db.execute(
        select(
            CropActivity.cycle_id,
            func.count(),
            func.count().filter(CropActivity.status.in_(FINISHED)),
        )
        .where(CropActivity.cycle_id.in_(cycle_ids))
        .group_by(CropActivity.cycle_id)
    ):
        figures[cycle_id].tasks, figures[cycle_id].finished_tasks = total, finished
    for cycle_id, result, count in db.execute(
        select(Diagnosis.cycle_id, Diagnosis.result_status, func.count())
        .where(Diagnosis.cycle_id.in_(cycle_ids))
        .group_by(Diagnosis.cycle_id, Diagnosis.result_status)
    ):
        figures[cycle_id].scans[result] = count
    for cycle_id, disease_name, count in db.execute(
        select(Diagnosis.cycle_id, Disease.disease_name, func.count())
        .join(Disease, Disease.disease_id == Diagnosis.disease_id)
        .where(Diagnosis.cycle_id.in_(cycle_ids), Diagnosis.result_status == ResultStatus.DISEASED)
        .group_by(Diagnosis.cycle_id, Disease.disease_name)
    ):
        figures[cycle_id].diseases[disease_name] = count
    return list(figures.values())


def _scan_counts(counter: Counter) -> ScanCounts:
    return ScanCounts(
        diseased=counter[ResultStatus.DISEASED],
        healthy=counter[ResultStatus.HEALTHY],
        unrecognized=counter[ResultStatus.UNRECOGNIZED],
    )


def farm_report(
    db: Session,
    user: User,
    farm_id: int,
    season: CropSeason | None,
    season_year: int | None,
) -> FarmReport:
    """Per field and in total for one season; farm owners only.

    Errors: 403 not_farm_member (also for a farm that does not exist), not_farm_owner;
    422 season_incomplete.
    """
    role = require_farm_member(db, user, farm_id)
    if role != FarmRole.OWNER:
        raise AppError(403, "not_farm_owner")
    season, season_year = _season(season, season_year)

    figures = cycle_figures(db, farm_id, season, season_year)
    where = expense_service.SeasonFilter(farm_id, role, season, season_year, None)
    summary = expense_service.summary(db, where)
    fields = [
        FieldReport(
            field_name=f.field_name,
            crop_name=f.crop_name,
            variety_name=f.variety_name,
            area_ha=f.cycle.area_planted_ha,
            planting_date=f.cycle.planting_date,
            status=f.cycle.status,
            expenses_php=f.expenses,
            harvest_kg=f.harvest_kg,
            gross_income_php=f.gross,
            net_profit_php=f.gross - f.expenses,
            actual_yield_t_ha=(
                _yield_t_ha(f.harvest_kg, f.cycle.area_planted_ha) if f.has_harvest else None
            ),
            task_completion_pct=completion_pct(f.finished_tasks, f.tasks),
            scans=_scan_counts(f.scans),
            top_disease=next((name for name, _ in _top(f.diseases)), None),
        )
        for f in figures
    ]
    return FarmReport(
        farm_name=db.scalar(select(Farm.farm_name).where(Farm.farm_id == farm_id)),
        season=season,
        season_year=season_year,
        fields=fields,
        totals=ReportTotals(
            area_ha=sum((f.cycle.area_planted_ha for f in figures), _ZERO),
            expenses_php=summary.total_expenses_php,
            whole_farm_expenses_php=summary.whole_farm_expenses_php,
            harvest_kg=sum((f.harvest_kg for f in figures), _ZERO),
            gross_income_php=summary.gross_income_php,
            net_profit_php=summary.net_profit_php,
        ),
    )


@dataclass
class _CropSum:
    crop_name: str
    cycles: int = 0
    area: Decimal = _ZERO
    harvested_cycles: int = 0
    harvest_kg: Decimal = _ZERO
    harvested_area: Decimal = _ZERO  # area of cycles with at least one harvest


def _season_scans(db: Session, season: CropSeason, season_year: int, municipality: str | None):
    """Scans dated in the season, placed by the cycle's farm or, without a cycle, by the
    scanning member's municipality."""
    start, end = season_dates(season, season_year)
    place = func.coalesce(Barangay.municipality, User.municipality)
    query = (
        select(Diagnosis.result_status, Crop.crop_name, Disease.disease_name)
        .join(User, User.user_id == Diagnosis.user_id)
        .join(Crop, Crop.crop_id == Diagnosis.crop_id)
        .outerjoin(Disease, Disease.disease_id == Diagnosis.disease_id)
        .outerjoin(CropCycle, CropCycle.cycle_id == Diagnosis.cycle_id)
        .outerjoin(FarmField, FarmField.field_id == CropCycle.field_id)
        .outerjoin(Farm, Farm.farm_id == FarmField.farm_id)
        .outerjoin(Barangay, Barangay.barangay_id == Farm.barangay_id)
        .where(
            Diagnosis.created_at >= philippine_midnight(start),
            Diagnosis.created_at < philippine_midnight(end),
        )
    )
    if municipality is not None:
        query = query.where(place == municipality)
    return db.execute(query).all()


def cooperative_report(
    db: Session,
    season: CropSeason | None,
    season_year: int | None,
    municipality: str | None,
) -> CooperativeReport:
    """Farm results rolled up by crop, with the season's scans; no names or contact details.

    Errors: 422 season_incomplete, unknown_municipality.
    """
    season, season_year = _season(season, season_year)
    if municipality is not None and municipality not in MUNICIPALITIES:
        raise AppError(422, "unknown_municipality")

    members = select(func.count()).where(
        User.role == UserRole.MEMBER, User.account_status == AccountStatus.ACTIVE
    )
    farms_query = select(Farm.farm_id).order_by(Farm.farm_id)
    if municipality is not None:
        members = members.where(User.municipality == municipality)
        farms_query = farms_query.join(Barangay, Barangay.barangay_id == Farm.barangay_id).where(
            Barangay.municipality == municipality
        )

    crops: dict[int, _CropSum] = {}
    farm_count = 0
    for farm_id in db.scalars(farms_query):
        figures = cycle_figures(db, farm_id, season, season_year)
        if figures:
            farm_count += 1
        for f in figures:
            crop = crops.setdefault(f.crop_id, _CropSum(f.crop_name))
            crop.cycles += 1
            crop.area += f.cycle.area_planted_ha
            crop.harvested_cycles += f.cycle.status == CycleStatus.HARVESTED
            if f.has_harvest:
                crop.harvest_kg += f.harvest_kg
                crop.harvested_area += f.cycle.area_planted_ha

    scans: Counter = Counter()
    diseases: defaultdict[tuple[str, str], int] = defaultdict(int)
    for result, crop_name, disease_name in _season_scans(db, season, season_year, municipality):
        scans[result] += 1
        if result == ResultStatus.DISEASED and disease_name is not None:
            diseases[(crop_name, disease_name)] += 1

    return CooperativeReport(
        season=season,
        season_year=season_year,
        active_members=db.scalar(members),
        farms=farm_count,
        by_crop=[
            CropTotals(
                crop_name=crop.crop_name,
                cycles=crop.cycles,
                area_ha=crop.area,
                harvested_cycles=crop.harvested_cycles,
                harvest_kg=crop.harvest_kg,
                avg_yield_t_ha=(
                    _yield_t_ha(crop.harvest_kg, crop.harvested_area)
                    if crop.harvested_area
                    else None
                ),
            )
            for _, crop in sorted(crops.items())
        ],
        diseases=[
            DiseaseCount(crop_name=crop_name, disease_name=disease_name, scans=count)
            for (crop_name, disease_name), count in sorted(
                diseases.items(), key=lambda item: (-item[1], item[0][1], item[0][0])
            )
        ],
        scans=_scan_counts(scans),
    )
