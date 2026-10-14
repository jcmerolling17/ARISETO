"""CROP and CROP_VARIETY lookup (read-only; varieties come from the seed command)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Crop, CropVariety
from app.schemas.crop import CropOut, VarietyOut


def list_crops(db: Session) -> list[CropOut]:
    """Every crop in scope with its varieties, both alphabetically. A crop with no varieties
    yet has an empty list."""
    varieties: dict[int, list[VarietyOut]] = {}
    for variety in db.scalars(select(CropVariety).order_by(CropVariety.variety_name)):
        varieties.setdefault(variety.crop_id, []).append(VarietyOut.model_validate(variety))
    return [
        CropOut(
            crop_id=crop.crop_id,
            crop_name=crop.crop_name,
            varieties=varieties.get(crop.crop_id, []),
        )
        for crop in db.scalars(select(Crop).order_by(Crop.crop_name))
    ]
