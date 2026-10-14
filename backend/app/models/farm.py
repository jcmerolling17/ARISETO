from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import FarmRole, farm_role


class Farm(Base):
    """FARM: location comes from its barangay; the registering member becomes its owner."""

    __tablename__ = "farm"
    __table_args__ = (CheckConstraint("total_area_ha > 0", name="total_area_ha_positive"),)

    farm_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    barangay_id: Mapped[int] = mapped_column(ForeignKey("barangay.barangay_id"))
    farm_name: Mapped[str] = mapped_column(String(100))
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    total_area_ha: Mapped[Decimal] = mapped_column(Numeric(10, 4))


class FarmAssignment(Base):
    """FARM_ASSIGNMENT: resolves USER-FARM, including ownership (at least one owner per farm,
    enforced in the API)."""

    __tablename__ = "farm_assignment"
    __table_args__ = (UniqueConstraint("farm_id", "user_id"),)

    assignment_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farm.farm_id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    role_on_farm: Mapped[FarmRole] = mapped_column(farm_role)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
