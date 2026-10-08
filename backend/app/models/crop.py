from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import CROPS_IN_SCOPE, sql_in_list
from app.db.base import Base
from app.models.enums import (
    CropSeason,
    CycleStatus,
    MaturityClass,
    crop_season,
    cycle_status,
    maturity_class,
)


class Crop(Base):
    """CROP: limited by scope to rice, corn, and onion."""

    __tablename__ = "crop"
    __table_args__ = (
        CheckConstraint(f"lower(crop_name) IN {sql_in_list(CROPS_IN_SCOPE)}", name="in_scope"),
    )

    crop_id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True), primary_key=True)
    crop_name: Mapped[str] = mapped_column(String(30), unique=True)


class CropVariety(Base):
    __tablename__ = "crop_variety"
    __table_args__ = (
        UniqueConstraint("crop_id", "variety_name"),
        CheckConstraint("maturity_days > 0", name="maturity_days_positive"),
    )

    variety_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    crop_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("crop.crop_id"))
    variety_name: Mapped[str] = mapped_column(String(80))
    maturity_class: Mapped[MaturityClass] = mapped_column(maturity_class)
    maturity_days: Mapped[int] = mapped_column(SmallInteger)


class CropCycle(Base):
    """CROP_CYCLE: one planting season on one farm. area_planted_ha <= FARM.total_area_ha,
    the planting-date window, and expected_harvest_date are enforced by the API."""

    __tablename__ = "crop_cycle"
    __table_args__ = (CheckConstraint("area_planted_ha > 0", name="area_planted_ha_positive"),)

    cycle_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farm.farm_id"))
    variety_id: Mapped[int] = mapped_column(ForeignKey("crop_variety.variety_id"))
    season: Mapped[CropSeason] = mapped_column(crop_season)
    area_planted_ha: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    planting_date: Mapped[date] = mapped_column(Date)
    expected_harvest_date: Mapped[date] = mapped_column(Date)
    actual_harvest_date: Mapped[date | None] = mapped_column(Date)
    target_yield_t_ha: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    status: Mapped[CycleStatus] = mapped_column(cycle_status)
