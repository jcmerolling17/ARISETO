from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.core.constants import CROPS_IN_SCOPE
from app.models.enums import CropSeason, PlantingMethod


def _collapse_spaces(value: str) -> str:
    return " ".join(value.split())


def _crop_in_scope(value: str) -> str:
    if value not in CROPS_IN_SCOPE:
        raise ValueError(f"must be one of {', '.join(CROPS_IN_SCOPE)}")
    return value


# Trimmed text with inner spaces collapsed.
FarmName = Annotated[
    str, AfterValidator(_collapse_spaces), StringConstraints(min_length=1, max_length=100)
]
FieldName = Annotated[
    str, AfterValidator(_collapse_spaces), StringConstraints(min_length=1, max_length=50)
]
VarietyName = Annotated[
    str, AfterValidator(_collapse_spaces), StringConstraints(min_length=1, max_length=80)
]

# NUMERIC(10,4) hectares and NUMERIC(9,6) degrees.
Hectares = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=4)]
Degrees = Annotated[Decimal, Field(max_digits=9, decimal_places=6)]


class FarmCreate(BaseModel):
    """POST /farms body. total_area_ha is the sum of the fields entered during setup;
    latitude/longitude are the barangay's center point."""

    model_config = ConfigDict(extra="forbid")

    farm_name: FarmName
    barangay_id: int
    latitude: Degrees
    longitude: Degrees
    total_area_ha: Hectares


class FarmOut(BaseModel):
    """POST /farms response. Numbers are JSON numbers."""

    model_config = ConfigDict(from_attributes=True)

    farm_id: int
    farm_name: str
    barangay_id: int
    latitude: float
    longitude: float
    total_area_ha: float


class FieldCreate(BaseModel):
    """POST /farms/{farm_id}/fields body, as the farm setup screen sends it."""

    model_config = ConfigDict(extra="forbid")

    field_name: FieldName
    crop: Annotated[str, AfterValidator(_crop_in_scope)]
    variety: VarietyName
    area_ha: Hectares
    planting_date: date
    planting_method: PlantingMethod
    season: CropSeason


class FieldOut(BaseModel):
    field_id: int
    farm_id: int
    field_name: str
    crop: str
    variety: str
    area_ha: float
    planting_date: date
    planting_method: PlantingMethod
    season: CropSeason
