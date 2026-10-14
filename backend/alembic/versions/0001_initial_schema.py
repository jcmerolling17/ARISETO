"""Initial schema: users, barangay, farm, farm_assignment, crop, crop_variety, crop_cycle,
calendar_template_task, crop_activity, weather_log.

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MUNICIPALITIES_SQL = (
    "('Abra de Ilog', 'Calintaan', 'Looc', 'Lubang', 'Magsaysay', 'Mamburao', "
    "'Paluan', 'Rizal', 'Sablayan', 'San Jose', 'Santa Cruz')"
)

# Native enum types (Section 4). create_type=False: created explicitly below so the
# migration owns their lifecycle.
user_role = postgresql.ENUM("member", "coop_admin", name="user_role", create_type=False)
language_code = postgresql.ENUM("fil", "en", name="language_code", create_type=False)
account_status = postgresql.ENUM(
    "pending", "active", "deactivated", name="account_status", create_type=False
)
farm_role = postgresql.ENUM(
    "owner", "operator", "tenant", "worker", name="farm_role", create_type=False
)
maturity_class = postgresql.ENUM(
    "early", "medium", "late", name="maturity_class", create_type=False
)
crop_season = postgresql.ENUM("wet", "dry", name="crop_season", create_type=False)
cycle_status = postgresql.ENUM(
    "planned", "active", "harvested", "failed", name="cycle_status", create_type=False
)
task_type = postgresql.ENUM(
    "land_prep",
    "planting",
    "fertilization",
    "irrigation",
    "pest_control",
    "weeding",
    "harvest",
    "other",
    name="task_type",
    create_type=False,
)
activity_status = postgresql.ENUM(
    "pending", "done", "skipped", "rescheduled", name="activity_status", create_type=False
)

ENUMS = (
    user_role,
    language_code,
    account_status,
    farm_role,
    maturity_class,
    crop_season,
    cycle_status,
    task_type,
    activity_status,
)


def identity() -> sa.Identity:
    return sa.Identity(always=True)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUMS:
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "barangay",
        sa.Column("barangay_id", sa.Integer(), identity(), nullable=False),
        sa.Column("psgc_code", sa.String(10), nullable=False),
        sa.Column("municipality", sa.String(80), nullable=False),
        sa.Column("barangay_name", sa.String(100), nullable=False),
        sa.Column("center_latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("center_longitude", sa.Numeric(9, 6), nullable=False),
        sa.CheckConstraint(
            f"municipality IN {MUNICIPALITIES_SQL}", name=op.f("ck_barangay_municipality")
        ),
        sa.PrimaryKeyConstraint("barangay_id", name=op.f("pk_barangay")),
        sa.UniqueConstraint("psgc_code", name=op.f("uq_barangay_psgc_code")),
        sa.UniqueConstraint(
            "municipality", "barangay_name", name=op.f("uq_barangay_municipality_barangay_name")
        ),
    )

    op.create_table(
        "users",
        sa.Column("user_id", sa.Integer(), identity(), nullable=False),
        sa.Column("member_no", sa.String(20), nullable=True),
        sa.Column("first_name", sa.String(60), nullable=False),
        sa.Column("last_name", sa.String(60), nullable=False),
        sa.Column("mobile_no", sa.String(13), nullable=False),
        sa.Column("email", sa.String(120), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, server_default="member", nullable=False),
        sa.Column("barangay_id", sa.Integer(), nullable=True),
        sa.Column("municipality", sa.String(80), nullable=False),
        sa.Column("preferred_language", language_code, server_default="fil", nullable=False),
        sa.Column("account_status", account_status, server_default="pending", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("mobile_no ~ '^\\+639[0-9]{9}$'", name=op.f("ck_users_mobile_no_format")),
        sa.CheckConstraint(
            "role <> 'member' OR member_no IS NOT NULL",
            name=op.f("ck_users_member_no_required_for_member"),
        ),
        sa.CheckConstraint(
            f"municipality IN {MUNICIPALITIES_SQL}", name=op.f("ck_users_municipality")
        ),
        sa.ForeignKeyConstraint(
            ["barangay_id"],
            ["barangay.barangay_id"],
            name=op.f("fk_users_barangay_id_barangay"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("member_no", name=op.f("uq_users_member_no")),
        sa.UniqueConstraint("mobile_no", name=op.f("uq_users_mobile_no")),
    )

    op.create_table(
        "farm",
        sa.Column("farm_id", sa.Integer(), identity(), nullable=False),
        sa.Column("barangay_id", sa.Integer(), nullable=False),
        sa.Column("farm_name", sa.String(100), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("total_area_ha", sa.Numeric(10, 4), nullable=False),
        sa.CheckConstraint("total_area_ha > 0", name=op.f("ck_farm_total_area_ha_positive")),
        sa.ForeignKeyConstraint(
            ["barangay_id"], ["barangay.barangay_id"], name=op.f("fk_farm_barangay_id_barangay")
        ),
        sa.PrimaryKeyConstraint("farm_id", name=op.f("pk_farm")),
    )

    op.create_table(
        "farm_assignment",
        sa.Column("assignment_id", sa.Integer(), identity(), nullable=False),
        sa.Column("farm_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_on_farm", farm_role, nullable=False),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"], ["farm.farm_id"], name=op.f("fk_farm_assignment_farm_id_farm")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.user_id"], name=op.f("fk_farm_assignment_user_id_users")
        ),
        sa.PrimaryKeyConstraint("assignment_id", name=op.f("pk_farm_assignment")),
        sa.UniqueConstraint(
            "farm_id", "user_id", name=op.f("uq_farm_assignment_farm_id_user_id")
        ),
    )

    op.create_table(
        "crop",
        sa.Column("crop_id", sa.SmallInteger(), identity(), nullable=False),
        sa.Column("crop_name", sa.String(30), nullable=False),
        sa.CheckConstraint(
            "lower(crop_name) IN ('rice', 'corn', 'onion')", name=op.f("ck_crop_in_scope")
        ),
        sa.PrimaryKeyConstraint("crop_id", name=op.f("pk_crop")),
        sa.UniqueConstraint("crop_name", name=op.f("uq_crop_crop_name")),
    )

    op.create_table(
        "crop_variety",
        sa.Column("variety_id", sa.Integer(), identity(), nullable=False),
        sa.Column("crop_id", sa.SmallInteger(), nullable=False),
        sa.Column("variety_name", sa.String(80), nullable=False),
        sa.Column("maturity_class", maturity_class, nullable=False),
        sa.Column("maturity_days", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "maturity_days > 0", name=op.f("ck_crop_variety_maturity_days_positive")
        ),
        sa.ForeignKeyConstraint(
            ["crop_id"], ["crop.crop_id"], name=op.f("fk_crop_variety_crop_id_crop")
        ),
        sa.PrimaryKeyConstraint("variety_id", name=op.f("pk_crop_variety")),
        sa.UniqueConstraint(
            "crop_id", "variety_name", name=op.f("uq_crop_variety_crop_id_variety_name")
        ),
    )

    op.create_table(
        "crop_cycle",
        sa.Column("cycle_id", sa.Integer(), identity(), nullable=False),
        sa.Column("farm_id", sa.Integer(), nullable=False),
        sa.Column("variety_id", sa.Integer(), nullable=False),
        sa.Column("season", crop_season, nullable=False),
        sa.Column("area_planted_ha", sa.Numeric(10, 4), nullable=False),
        sa.Column("planting_date", sa.Date(), nullable=False),
        sa.Column("expected_harvest_date", sa.Date(), nullable=False),
        sa.Column("actual_harvest_date", sa.Date(), nullable=True),
        sa.Column("target_yield_t_ha", sa.Numeric(6, 2), nullable=True),
        sa.Column("status", cycle_status, nullable=False),
        sa.CheckConstraint(
            "area_planted_ha > 0", name=op.f("ck_crop_cycle_area_planted_ha_positive")
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"], ["farm.farm_id"], name=op.f("fk_crop_cycle_farm_id_farm")
        ),
        sa.ForeignKeyConstraint(
            ["variety_id"],
            ["crop_variety.variety_id"],
            name=op.f("fk_crop_cycle_variety_id_crop_variety"),
        ),
        sa.PrimaryKeyConstraint("cycle_id", name=op.f("pk_crop_cycle")),
    )

    op.create_table(
        "calendar_template_task",
        sa.Column("template_task_id", sa.Integer(), identity(), nullable=False),
        sa.Column("variety_id", sa.Integer(), nullable=False),
        sa.Column("week_no", sa.SmallInteger(), nullable=False),
        sa.Column("task_type", task_type, nullable=False),
        sa.Column("task_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_weather_sensitive", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["variety_id"],
            ["crop_variety.variety_id"],
            name=op.f("fk_calendar_template_task_variety_id_crop_variety"),
        ),
        sa.PrimaryKeyConstraint("template_task_id", name=op.f("pk_calendar_template_task")),
    )

    op.create_table(
        "crop_activity",
        sa.Column("activity_id", sa.Integer(), identity(), nullable=False),
        sa.Column("cycle_id", sa.Integer(), nullable=False),
        sa.Column("template_task_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("status", activity_status, server_default="pending", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_uuid", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["crop_cycle.cycle_id"], name=op.f("fk_crop_activity_cycle_id_crop_cycle")
        ),
        sa.ForeignKeyConstraint(
            ["template_task_id"],
            ["calendar_template_task.template_task_id"],
            name=op.f("fk_crop_activity_template_task_id_calendar_template_task"),
        ),
        sa.PrimaryKeyConstraint("activity_id", name=op.f("pk_crop_activity")),
        sa.UniqueConstraint("client_uuid", name=op.f("uq_crop_activity_client_uuid")),
    )

    op.create_table(
        "weather_log",
        sa.Column("weather_id", sa.BigInteger(), identity(), nullable=False),
        sa.Column("farm_id", sa.Integer(), nullable=False),
        sa.Column("forecast_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temp_c", sa.Numeric(), nullable=True),
        sa.Column("feels_like_c", sa.Numeric(4, 1), nullable=True),
        sa.Column("humidity_pct", sa.SmallInteger(), nullable=True),
        sa.Column("rain_mm", sa.Numeric(), nullable=True),
        sa.Column("precip_probability_pct", sa.SmallInteger(), nullable=True),
        sa.Column("wind_speed_mps", sa.Numeric(), nullable=True),
        sa.Column("condition_code", sa.SmallInteger(), nullable=False),
        sa.Column("is_forecast", sa.Boolean(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "humidity_pct BETWEEN 0 AND 100", name=op.f("ck_weather_log_humidity_pct_range")
        ),
        sa.CheckConstraint(
            "precip_probability_pct BETWEEN 0 AND 100",
            name=op.f("ck_weather_log_precip_probability_pct_range"),
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"], ["farm.farm_id"], name=op.f("fk_weather_log_farm_id_farm")
        ),
        sa.PrimaryKeyConstraint("weather_id", name=op.f("pk_weather_log")),
    )


def downgrade() -> None:
    for table in (
        "weather_log",
        "crop_activity",
        "calendar_template_task",
        "crop_cycle",
        "crop_variety",
        "crop",
        "farm_assignment",
        "farm",
        "users",
        "barangay",
    ):
        op.drop_table(table)

    bind = op.get_bind()
    for enum_type in reversed(ENUMS):
        enum_type.drop(bind, checkfirst=False)
