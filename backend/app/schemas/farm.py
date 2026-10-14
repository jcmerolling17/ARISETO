from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import CropSeason, FarmRole


def _collapse_spaces(value: str) -> str:
    return " ".join(value.split())


# Trimmed text with inner spaces collapsed.
FarmName = Annotated[
    str, AfterValidator(_collapse_spaces), StringConstraints(min_length=1, max_length=100)
]
FieldName = Annotated[
    str, AfterValidator(_collapse_spaces), StringConstraints(min_length=1, max_length=50)
]

# NUMERIC(10,4) hectares and NUMERIC(6,2) tons per hectare.
Hectares = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=4)]
TonsPerHectare = Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)]


class SetupField(BaseModel):
    """One field in the POST /farms body; planting_date is the sowing date."""

    model_config = ConfigDict(extra="forbid")

    field_name: FieldName
    area_ha: Hectares
    variety_id: int
    planting_date: date


class FarmCreate(BaseModel):
    """POST /farms body. The backend sets the location from the barangay center and
    total_area_ha from the fields; an empty fields list is 422 no_fields."""

    model_config = ConfigDict(extra="forbid")

    farm_name: FarmName
    barangay_id: int
    season: CropSeason
    fields: list[SetupField]


class CreatedField(BaseModel):
    field_id: int
    cycle_id: int
    expected_harvest_date: date


class FarmCreated(BaseModel):
    """POST /farms response. Numbers are JSON numbers."""

    farm_id: int
    total_area_ha: float
    fields: list[CreatedField]


class FieldCreate(BaseModel):
    """POST /farms/{farm_id}/fields body; planting_date is the sowing date."""

    model_config = ConfigDict(extra="forbid")

    field_name: FieldName
    area_ha: Hectares
    variety_id: int
    season: CropSeason
    planting_date: date
    target_yield_t_ha: TonsPerHectare | None = None


class FieldCreated(CreatedField):
    """POST /farms/{farm_id}/fields response, with the farm's new total area."""

    total_area_ha: float


class FarmSummary(BaseModel):
    """GET /farms item: a farm the caller owns or works on, with their role on it.
    barangay_name and municipality come from BARANGAY, so the app can name the place its
    weather is for (the barangay center)."""

    farm_id: int
    farm_name: str
    barangay_id: int
    barangay_name: str
    municipality: str
    latitude: float
    longitude: float
    total_area_ha: float
    role_on_farm: FarmRole
