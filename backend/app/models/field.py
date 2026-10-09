from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import CropSeason, PlantingMethod, crop_season, planting_method


class FarmField(Base):
    """FIELD: one plot of a farm, added during farm setup. Field names are unique per farm
    (ignoring case), and the fields' areas may not add up to more than FARM.total_area_ha
    (enforced by the API).

    The variety is free text and the season and planting date are kept here until the
    variety list (CROP_VARIETY with maturity days) is available for CROP_CYCLE.
    """

    __tablename__ = "field"
    __table_args__ = (
        CheckConstraint("area_ha > 0", name="area_ha_positive"),
        Index(
            "uq_field_farm_id_lower_field_name", "farm_id", text("lower(field_name)"), unique=True
        ),
    )

    field_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farm.farm_id"))
    field_name: Mapped[str] = mapped_column(String(50))
    crop_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("crop.crop_id"))
    variety_name: Mapped[str] = mapped_column(String(80))
    area_ha: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    planting_date: Mapped[date] = mapped_column(Date)
    planting_method: Mapped[PlantingMethod] = mapped_column(planting_method)
    season: Mapped[CropSeason] = mapped_column(crop_season)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
