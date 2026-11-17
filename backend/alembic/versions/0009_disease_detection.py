"""Disease detection (Section 4 Tables 11-13): disease, its ordered treatment steps, and
diagnosis, one row per scan (unrecognized results included). The knowledge base is loaded
from the team's CSV files with python -m app.cli import-diseases, so nothing is seeded here.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

pathogen_type = postgresql.ENUM(
    "fungal", "bacterial", "viral", "pest", "nutrient", "unknown",
    name="pathogen_type",
    create_type=False,
)
treatment_type = postgresql.ENUM(
    "cultural", "biological", "chemical", "preventive", name="treatment_type", create_type=False
)
result_status = postgresql.ENUM(
    "diseased", "healthy", "unrecognized", name="result_status", create_type=False
)
ENUMS = (pathogen_type, treatment_type, result_status)


def identity() -> sa.Identity:
    return sa.Identity(always=True)


def upgrade() -> None:
    for enum in ENUMS:
        enum.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "disease",
        sa.Column("disease_id", sa.Integer(), identity(), nullable=False),
        sa.Column("crop_id", sa.SmallInteger(), nullable=False),
        sa.Column("disease_name", sa.String(100), nullable=False),
        sa.Column("local_name", sa.String(100), nullable=True),
        sa.Column("model_class_label", sa.String(80), nullable=False),
        sa.Column("pathogen_type", pathogen_type, nullable=False),
        sa.Column("symptoms", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("description_fil", sa.Text(), nullable=True),
        sa.Column("impact_en", sa.Text(), nullable=True),
        sa.Column("impact_fil", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["crop_id"], ["crop.crop_id"], name=op.f("fk_disease_crop_id_crop")
        ),
        sa.PrimaryKeyConstraint("disease_id", name=op.f("pk_disease")),
        sa.UniqueConstraint("model_class_label", name=op.f("uq_disease_model_class_label")),
    )

    op.create_table(
        "treatment",
        sa.Column("treatment_id", sa.Integer(), identity(), nullable=False),
        sa.Column("disease_id", sa.Integer(), nullable=False),
        sa.Column("step_no", sa.SmallInteger(), nullable=False),
        sa.Column("treatment_type", treatment_type, nullable=False),
        sa.Column("instruction_en", sa.Text(), nullable=False),
        sa.Column("instruction_fil", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.String(255), nullable=False),
        sa.CheckConstraint("step_no > 0", name=op.f("ck_treatment_step_no_positive")),
        sa.ForeignKeyConstraint(
            ["disease_id"], ["disease.disease_id"], name=op.f("fk_treatment_disease_id_disease")
        ),
        sa.PrimaryKeyConstraint("treatment_id", name=op.f("pk_treatment")),
        sa.UniqueConstraint(
            "disease_id", "step_no", name=op.f("uq_treatment_disease_id_step_no")
        ),
    )

    op.create_table(
        "diagnosis",
        sa.Column("diagnosis_id", sa.BigInteger(), identity(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("crop_id", sa.SmallInteger(), nullable=False),
        sa.Column("cycle_id", sa.Integer(), nullable=True),
        sa.Column("disease_id", sa.Integer(), nullable=True),
        sa.Column("image_path", sa.String(255), nullable=False),
        sa.Column("predicted_label", sa.String(80), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("result_status", result_status, nullable=False),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name=op.f("ck_diagnosis_confidence_range")
        ),
        sa.CheckConstraint(
            "(result_status = 'diseased') = (disease_id IS NOT NULL)",
            name=op.f("ck_diagnosis_disease_with_diseased"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.user_id"], name=op.f("fk_diagnosis_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["crop_id"], ["crop.crop_id"], name=op.f("fk_diagnosis_crop_id_crop")
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["crop_cycle.cycle_id"], name=op.f("fk_diagnosis_cycle_id_crop_cycle")
        ),
        sa.ForeignKeyConstraint(
            ["disease_id"], ["disease.disease_id"], name=op.f("fk_diagnosis_disease_id_disease")
        ),
        sa.PrimaryKeyConstraint("diagnosis_id", name=op.f("pk_diagnosis")),
    )
    op.create_index(
        op.f("ix_diagnosis_user_id_created_at"), "diagnosis", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_diagnosis_user_id_created_at"), table_name="diagnosis")
    op.drop_table("diagnosis")
    op.drop_table("treatment")
    op.drop_table("disease")
    for enum in reversed(ENUMS):
        enum.drop(op.get_bind(), checkfirst=False)
