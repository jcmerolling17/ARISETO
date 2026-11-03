import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.enums import CropSeason, QuantityUnit

# NUMERIC(10,2) values: greater than 0, at most 99,999,999.99, two decimals.
Money = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
# EXPENSE.season_year: Size 4 (a four-digit year at most).
SeasonYear = Annotated[int, Field(ge=1, le=9999)]


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class ExpenseCategoryOut(BaseModel):
    category_id: int
    category_name: str


class ExpenseCreate(BaseModel):
    """POST /farms/{farm_id}/expenses body (Section 6). cycle_id left out means a whole-farm
    expense, which then needs season and season_year. unit goes with quantity."""

    model_config = ConfigDict(extra="forbid")

    category_id: int
    amount_php: Money
    expense_date: date
    description: Annotated[str | None, Field(max_length=255), AfterValidator(_blank_to_none)] = None
    cycle_id: int | None = None
    season: CropSeason | None = None
    season_year: SeasonYear | None = None
    quantity: Money | None = None
    unit: QuantityUnit | None = None
    client_uuid: uuid.UUID


class ExpenseCreated(BaseModel):
    expense_id: int
    season: CropSeason
    season_year: int


class ExpenseItem(BaseModel):
    """GET /farms/{farm_id}/expenses item. field_name is null for a whole-farm expense;
    can_delete is true for the member who recorded it and for the farm owner."""

    expense_id: int
    category_id: int
    category_name: str
    amount_php: float
    expense_date: date
    description: str | None
    quantity: float | None
    unit: QuantityUnit | None
    cycle_id: int | None
    field_name: str | None
    season: CropSeason
    season_year: int
    recorded_by_name: str
    can_delete: bool


class CategoryAmount(BaseModel):
    category_name: str
    amount_php: float


class SeasonSummary(BaseModel):
    """GET /farms/{farm_id}/summary body; net_profit_php is computed on request."""

    season: CropSeason
    season_year: int
    total_expenses_php: float
    whole_farm_expenses_php: float
    by_category: list[CategoryAmount]
    gross_income_php: float
    net_profit_php: float
