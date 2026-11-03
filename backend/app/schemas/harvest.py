from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from app.models.enums import CycleStatus
from app.schemas.expense import Money

# HARVEST_RECORD.gross_income_php is NUMERIC(12,2).
MAX_GROSS_INCOME = Decimal("9999999999.99")


class HarvestCreate(BaseModel):
    """POST /cycles/{cycle_id}/harvests body. final_harvest is required: true closes the
    cycle as 'harvested'."""

    model_config = ConfigDict(extra="forbid")

    harvest_date: date
    quantity_kg: Money
    unit_price_php: Money
    final_harvest: StrictBool

    @model_validator(mode="after")
    def _gross_income_fits(self) -> "HarvestCreate":
        if self.quantity_kg * self.unit_price_php > MAX_GROSS_INCOME:
            raise ValueError("quantity_kg times unit_price_php is too large")
        return self


class HarvestCreated(BaseModel):
    harvest_id: int
    gross_income_php: float
    cycle_status: CycleStatus


class HarvestItem(BaseModel):
    """GET /farms/{farm_id}/harvests item."""

    harvest_id: int
    cycle_id: int
    field_name: str
    crop_name: str
    harvest_date: date
    quantity_kg: float
    unit_price_php: float
    gross_income_php: float
