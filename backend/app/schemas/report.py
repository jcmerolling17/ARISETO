"""Farm report (DFD 7.5) and cooperative report (DFD 7.6) bodies, computed on request."""

from datetime import date

from pydantic import BaseModel

from app.models.enums import CropSeason, CycleStatus


class ScanCounts(BaseModel):
    diseased: int = 0
    healthy: int = 0
    unrecognized: int = 0


class FieldReport(BaseModel):
    """One crop cycle of the season on one field."""

    field_name: str
    crop_name: str
    variety_name: str
    area_ha: float
    planting_date: date
    status: CycleStatus
    expenses_php: float
    harvest_kg: float
    gross_income_php: float
    net_profit_php: float
    actual_yield_t_ha: float | None  # null before the first harvest
    task_completion_pct: int
    scans: ScanCounts
    top_disease: str | None


class ReportTotals(BaseModel):
    area_ha: float
    expenses_php: float
    whole_farm_expenses_php: float
    harvest_kg: float
    gross_income_php: float
    net_profit_php: float


class FarmReport(BaseModel):
    """GET /farms/{farm_id}/report; totals match GET /farms/{farm_id}/summary."""

    farm_name: str
    season: CropSeason
    season_year: int
    fields: list[FieldReport]
    totals: ReportTotals


class CropTotals(BaseModel):
    crop_name: str
    cycles: int
    area_ha: float
    harvested_cycles: int
    harvest_kg: float
    avg_yield_t_ha: float | None  # null when no cycle has a harvest


class DiseaseCount(BaseModel):
    crop_name: str
    disease_name: str
    scans: int


class CooperativeReport(BaseModel):
    """GET /admin/reports/cooperative; no member names or contact details."""

    season: CropSeason
    season_year: int
    active_members: int
    farms: int
    by_crop: list[CropTotals]
    diseases: list[DiseaseCount]
    scans: ScanCounts
