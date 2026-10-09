"""Farm fields: field table, planting_method enum, and the three crops in scope.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

planting_method = postgresql.ENUM(
    "transplanting", "direct_seeding", name="planting_method", create_type=False
)
crop_season = postgresql.ENUM("wet", "dry", name="crop_season", create_type=False)

# Reference rows: the crops in scope (ck_crop_in_scope). Varieties come later.
CROPS = ("Rice", "Corn", "Onion")


def upgrade() -> None:
    planting_method.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "field",
        sa.Column("field_id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("farm_id", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(50), nullable=False),
        sa.Column("crop_id", sa.SmallInteger(), nullable=False),
        sa.Column("variety_name", sa.String(80), nullable=False),
        sa.Column("area_ha", sa.Numeric(10, 4), nullable=False),
        sa.Column("planting_date", sa.Date(), nullable=False),
        sa.Column("planting_method", planting_method, nullable=False),
        sa.Column("season", crop_season, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("area_ha > 0", name=op.f("ck_field_area_ha_positive")),
        sa.ForeignKeyConstraint(["farm_id"], ["farm.farm_id"], name=op.f("fk_field_farm_id_farm")),
        sa.ForeignKeyConstraint(["crop_id"], ["crop.crop_id"], name=op.f("fk_field_crop_id_crop")),
        sa.PrimaryKeyConstraint("field_id", name=op.f("pk_field")),
    )
    op.create_index(
        "uq_field_farm_id_lower_field_name",
        "field",
        ["farm_id", sa.text("lower(field_name)")],
        unique=True,
    )

    crop = sa.table("crop", sa.column("crop_name", sa.String))
    op.bulk_insert(crop, [{"crop_name": name} for name in CROPS])


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM crop WHERE crop_name IN :names").bindparams(
            sa.bindparam("names", value=list(CROPS), expanding=True)
        )
    )
    op.drop_index("uq_field_farm_id_lower_field_name", table_name="field")
    op.drop_table("field")
    planting_method.drop(op.get_bind(), checkfirst=False)
