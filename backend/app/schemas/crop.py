from pydantic import BaseModel, ConfigDict

from app.models.enums import MaturityClass


class VarietyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variety_id: int
    variety_name: str
    maturity_class: MaturityClass
    maturity_days: int


class CropOut(BaseModel):
    """GET /crops item (Section 6): a crop with its varieties."""

    crop_id: int
    crop_name: str
    varieties: list[VarietyOut]
