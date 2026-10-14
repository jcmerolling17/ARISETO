from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FarmField(Base):
    """FIELD: one plot of a farm. Field names are unique per farm (ignoring case), and
    FARM.total_area_ha is the sum of the farm's field areas (kept by the API). The crop,
    variety, season, and sowing date belong to each CROP_CYCLE on the field."""

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
    area_ha: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
