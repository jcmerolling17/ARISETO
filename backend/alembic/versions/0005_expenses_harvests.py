"""Expenses and harvests (Section 4 Tables 15-17): expense_category with its seven
categories, expense (a field's crop cycle or the whole farm for a season), and
harvest_record with gross_income_php as a stored generated column.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

crop_season = postgresql.ENUM("wet", "dry", name="crop_season", create_type=False)
quantity_unit = postgresql.ENUM(
    "kg", "sack", "liter", "bag", "hour", name="quantity_unit", create_type=False
)

# Table 16, in the documented order (the list on the Add Expense screen).
CATEGORIES = ("Seeds", "Fertilizer", "Chemicals", "Labor", "Equipment", "Fuel", "Others")


def identity() -> sa.Identity:
    return sa.Identity(always=True)


def upgrade() -> None:
    quantity_unit.create(op.get_bind(), checkfirst=False)

    category = op.create_table(
        "expense_category",
        sa.Column("category_id", sa.SmallInteger(), identity(), nullable=False),
        sa.Column("category_name", sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint("category_id", name=op.f("pk_expense_category")),
        sa.UniqueConstraint("category_name", name=op.f("uq_expense_category_category_name")),
    )
    op.bulk_insert(category, [{"category_name": name} for name in CATEGORIES])

    op.create_table(
        "expense",
        sa.Column("expense_id", sa.Integer(), identity(), nullable=False),
        sa.Column("cycle_id", sa.Integer(), nullable=True),
        sa.Column("farm_id", sa.Integer(), nullable=False),
        sa.Column("season", crop_season, nullable=False),
        sa.Column("season_year", sa.SmallInteger(), nullable=False),
        sa.Column("category_id", sa.SmallInteger(), nullable=False),
        sa.Column("recorded_by", sa.Integer(), nullable=False),
        sa.Column("amount_php", sa.Numeric(10, 2), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=True),
        sa.Column("unit", quantity_unit, nullable=True),
        sa.Column("client_uuid", sa.Uuid(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_php > 0", name=op.f("ck_expense_amount_php_positive")),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0", name=op.f("ck_expense_quantity_positive")
        ),
        sa.CheckConstraint(
            "(quantity IS NULL) = (unit IS NULL)", name=op.f("ck_expense_unit_with_quantity")
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["crop_cycle.cycle_id"], name=op.f("fk_expense_cycle_id_crop_cycle")
        ),
        sa.ForeignKeyConstraint(["farm_id"], ["farm.farm_id"], name=op.f("fk_expense_farm_id_farm")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["expense_category.category_id"],
            name=op.f("fk_expense_category_id_expense_category"),
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"], ["users.user_id"], name=op.f("fk_expense_recorded_by_users")
        ),
        sa.PrimaryKeyConstraint("expense_id", name=op.f("pk_expense")),
        sa.UniqueConstraint("client_uuid", name=op.f("uq_expense_client_uuid")),
    )
    op.create_index(
        op.f("ix_expense_farm_id_season"), "expense", ["farm_id", "season", "season_year"]
    )

    op.create_table(
        "harvest_record",
        sa.Column("harvest_id", sa.Integer(), identity(), nullable=False),
        sa.Column("cycle_id", sa.Integer(), nullable=False),
        sa.Column("harvest_date", sa.Date(), nullable=False),
        sa.Column("quantity_kg", sa.Numeric(10, 2), nullable=False),
        sa.Column("unit_price_php", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "gross_income_php",
            sa.Numeric(12, 2),
            sa.Computed("quantity_kg * unit_price_php", persisted=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity_kg > 0", name=op.f("ck_harvest_record_quantity_kg_positive")
        ),
        sa.CheckConstraint(
            "unit_price_php > 0", name=op.f("ck_harvest_record_unit_price_php_positive")
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["crop_cycle.cycle_id"],
            name=op.f("fk_harvest_record_cycle_id_crop_cycle"),
        ),
        sa.PrimaryKeyConstraint("harvest_id", name=op.f("pk_harvest_record")),
    )


def downgrade() -> None:
    op.drop_table("harvest_record")
    op.drop_index(op.f("ix_expense_farm_id_season"), table_name="expense")
    op.drop_table("expense")
    op.drop_table("expense_category")
    quantity_unit.drop(op.get_bind(), checkfirst=False)
