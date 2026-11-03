import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import CropSeason, QuantityUnit, crop_season, quantity_unit


class ExpenseCategory(Base):
    """EXPENSE_CATEGORY: seeded with the seven categories (Table 16); read-only in the app."""

    __tablename__ = "expense_category"

    category_id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True), primary_key=True)
    category_name: Mapped[str] = mapped_column(String(50), unique=True)


class Expense(Base):
    """EXPENSE: one field's crop cycle (cycle_id set) or the whole farm for a season
    (cycle_id NULL). farm_id, season and season_year are always set, and match the cycle
    when there is one (kept by the API)."""

    __tablename__ = "expense"
    __table_args__ = (
        CheckConstraint("amount_php > 0", name="amount_php_positive"),
        CheckConstraint("quantity IS NULL OR quantity > 0", name="quantity_positive"),
        CheckConstraint("(quantity IS NULL) = (unit IS NULL)", name="unit_with_quantity"),
        Index("ix_expense_farm_id_season", "farm_id", "season", "season_year"),
    )

    expense_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("crop_cycle.cycle_id"))
    farm_id: Mapped[int] = mapped_column(ForeignKey("farm.farm_id"))
    season: Mapped[CropSeason] = mapped_column(crop_season)
    season_year: Mapped[int] = mapped_column(SmallInteger)
    category_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("expense_category.category_id")
    )
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    amount_php: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    expense_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    unit: Mapped[QuantityUnit | None] = mapped_column(quantity_unit)
    client_uuid: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    # Server save time; NULL only while an entry waits in the phone's offline queue.
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HarvestRecord(Base):
    """HARVEST_RECORD: one harvest of a crop cycle; several are allowed per cycle."""

    __tablename__ = "harvest_record"
    __table_args__ = (
        CheckConstraint("quantity_kg > 0", name="quantity_kg_positive"),
        CheckConstraint("unit_price_php > 0", name="unit_price_php_positive"),
    )

    harvest_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("crop_cycle.cycle_id"))
    harvest_date: Mapped[date] = mapped_column(Date)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    unit_price_php: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    gross_income_php: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), Computed("quantity_kg * unit_price_php", persisted=True)
    )
