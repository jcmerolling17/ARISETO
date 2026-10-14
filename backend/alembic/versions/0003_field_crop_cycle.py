"""Fields hold only their name and area; each crop cycle belongs to a field; no planting
method; 'very_early' maturity class (Section 4).

Upgrade adds crop_cycle.field_id as NOT NULL, so it stops if crop_cycle already has rows
(their field can't be known). Downgrade copies each field's crop, variety, sowing date, and
season back from its first crop cycle, and fails if a variety is 'very_early'.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

planting_method = postgresql.ENUM(
    "transplanting", "direct_seeding", name="planting_method", create_type=False
)
crop_season = postgresql.ENUM("wet", "dry", name="crop_season", create_type=False)

FIELD_CYCLE_COLUMNS = ("crop_id", "variety_name", "planting_date", "planting_method", "season")


def upgrade() -> None:
    op.drop_constraint("fk_field_crop_id_crop", "field", type_="foreignkey")
    for column in FIELD_CYCLE_COLUMNS:
        op.drop_column("field", column)
    planting_method.drop(op.get_bind(), checkfirst=False)

    op.drop_constraint("fk_crop_cycle_farm_id_farm", "crop_cycle", type_="foreignkey")
    op.drop_column("crop_cycle", "farm_id")
    op.add_column("crop_cycle", sa.Column("field_id", sa.Integer(), nullable=False))
    op.create_foreign_key(
        op.f("fk_crop_cycle_field_id_field"), "crop_cycle", "field", ["field_id"], ["field_id"]
    )

    op.execute("ALTER TYPE maturity_class ADD VALUE 'very_early' BEFORE 'early'")


def downgrade() -> None:
    # PostgreSQL can't drop an enum value, so rebuild the type without 'very_early'.
    op.execute("ALTER TYPE maturity_class RENAME TO maturity_class_0003")
    op.execute("CREATE TYPE maturity_class AS ENUM ('early', 'medium', 'late')")
    op.execute(
        "ALTER TABLE crop_variety ALTER COLUMN maturity_class "
        "TYPE maturity_class USING maturity_class::text::maturity_class"
    )
    op.execute("DROP TYPE maturity_class_0003")

    planting_method.create(op.get_bind(), checkfirst=False)
    op.add_column("field", sa.Column("crop_id", sa.SmallInteger(), nullable=True))
    op.add_column("field", sa.Column("variety_name", sa.String(80), nullable=True))
    op.add_column("field", sa.Column("planting_date", sa.Date(), nullable=True))
    op.add_column("field", sa.Column("planting_method", planting_method, nullable=True))
    op.add_column("field", sa.Column("season", crop_season, nullable=True))
    # Every member direct-seeds (Section 4), so restored fields get 'direct_seeding'.
    op.execute(
        """
        UPDATE field AS f
        SET crop_id = v.crop_id,
            variety_name = v.variety_name,
            planting_date = c.planting_date,
            planting_method = 'direct_seeding',
            season = c.season
        FROM (
            SELECT DISTINCT ON (field_id) field_id, variety_id, planting_date, season
            FROM crop_cycle
            ORDER BY field_id, cycle_id
        ) AS c
        JOIN crop_variety AS v ON v.variety_id = c.variety_id
        WHERE c.field_id = f.field_id
        """
    )
    for column in FIELD_CYCLE_COLUMNS:
        op.alter_column("field", column, nullable=False)
    op.create_foreign_key("fk_field_crop_id_crop", "field", "crop", ["crop_id"], ["crop_id"])

    op.add_column("crop_cycle", sa.Column("farm_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE crop_cycle AS c SET farm_id = f.farm_id FROM field AS f "
        "WHERE f.field_id = c.field_id"
    )
    op.alter_column("crop_cycle", "farm_id", nullable=False)
    op.create_foreign_key(
        "fk_crop_cycle_farm_id_farm", "crop_cycle", "farm", ["farm_id"], ["farm_id"]
    )
    op.drop_constraint("fk_crop_cycle_field_id_field", "crop_cycle", type_="foreignkey")
    op.drop_column("crop_cycle", "field_id")
