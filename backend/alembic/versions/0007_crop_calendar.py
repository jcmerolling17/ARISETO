"""Crop calendar (Section 4 Tables 9, 10 and 24; Section 6 "Crop calendar (Phase 7)"):
calendar_template_task timed in days from sowing or harvest (replacing week_no), the task
details on crop_activity, and notification.activity_id for task reminders.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

task_type = postgresql.ENUM(name="task_type", create_type=False)
calendar_anchor = postgresql.ENUM("sowing", "harvest", name="calendar_anchor", create_type=False)
growth_stage = postgresql.ENUM(
    "land_preparation",
    "seed_sowing",
    "vegetative",
    "reproductive",
    "harvest",
    name="growth_stage",
    create_type=False,
)

TEMPLATE = "calendar_template_task"
ACTIVITY = "crop_activity"


def upgrade() -> None:
    calendar_anchor.create(op.get_bind(), checkfirst=False)
    growth_stage.create(op.get_bind(), checkfirst=False)

    # Templates were never seeded before Phase 7, so the new required columns need no default.
    op.drop_column(TEMPLATE, "week_no")
    op.add_column(TEMPLATE, sa.Column("anchor", calendar_anchor, nullable=False))
    op.add_column(TEMPLATE, sa.Column("day_offset", sa.SmallInteger(), nullable=False))
    op.add_column(TEMPLATE, sa.Column("day_offset_end", sa.SmallInteger(), nullable=True))
    op.add_column(TEMPLATE, sa.Column("repeat_every_days", sa.SmallInteger(), nullable=True))
    op.add_column(TEMPLATE, sa.Column("repeat_until_anchor", calendar_anchor, nullable=True))
    op.add_column(TEMPLATE, sa.Column("repeat_until_offset", sa.SmallInteger(), nullable=True))
    op.add_column(TEMPLATE, sa.Column("growth_stage", growth_stage, nullable=False))
    op.add_column(TEMPLATE, sa.Column("source_reference", sa.String(255), nullable=False))
    op.create_check_constraint(
        op.f("ck_calendar_template_task_day_offset_end_order"),
        TEMPLATE,
        "day_offset_end IS NULL OR day_offset_end >= day_offset",
    )
    op.create_check_constraint(
        op.f("ck_calendar_template_task_repeat_columns_together"),
        TEMPLATE,
        "(repeat_every_days IS NULL) = (repeat_until_anchor IS NULL) "
        "AND (repeat_every_days IS NULL) = (repeat_until_offset IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_calendar_template_task_repeat_every_days_positive"),
        TEMPLATE,
        "repeat_every_days IS NULL OR repeat_every_days > 0",
    )
    op.create_unique_constraint(
        op.f("uq_calendar_template_task_variety_id_anchor_day_offset_task_name"),
        TEMPLATE,
        ["variety_id", "anchor", "day_offset", "task_name"],
    )

    op.add_column(ACTIVITY, sa.Column("end_date", sa.Date(), nullable=True))
    op.add_column(ACTIVITY, sa.Column("scheduled_time", sa.Time(), nullable=True))
    op.add_column(
        ACTIVITY, sa.Column("reminder", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column(ACTIVITY, sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(ACTIVITY, sa.Column("notes", sa.String(500), nullable=True))
    op.add_column(
        ACTIVITY, sa.Column("task_type", task_type, server_default="other", nullable=False)
    )
    op.add_column(ACTIVITY, sa.Column("growth_stage", growth_stage, nullable=True))
    op.add_column(
        ACTIVITY,
        sa.Column("is_weather_sensitive", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_crop_activity_end_date_order"),
        ACTIVITY,
        "end_date IS NULL OR end_date >= scheduled_date",
    )

    op.add_column("notification", sa.Column("activity_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_notification_activity_id_crop_activity"),
        "notification",
        ACTIVITY,
        ["activity_id"],
        ["activity_id"],
    )
    op.create_check_constraint(
        op.f("ck_notification_activity_id_with_type"),
        "notification",
        "(type = 'task_reminder') = (activity_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_notification_activity_id_with_type"), "notification", type_="check"
    )
    op.drop_constraint(
        op.f("fk_notification_activity_id_crop_activity"), "notification", type_="foreignkey"
    )
    op.drop_column("notification", "activity_id")

    op.drop_constraint(op.f("ck_crop_activity_end_date_order"), ACTIVITY, type_="check")
    for column in (
        "is_weather_sensitive",
        "growth_stage",
        "task_type",
        "notes",
        "reminded_at",
        "reminder",
        "scheduled_time",
        "end_date",
    ):
        op.drop_column(ACTIVITY, column)

    op.drop_constraint(
        op.f("uq_calendar_template_task_variety_id_anchor_day_offset_task_name"),
        TEMPLATE,
        type_="unique",
    )
    for name in ("repeat_every_days_positive", "repeat_columns_together", "day_offset_end_order"):
        op.drop_constraint(op.f(f"ck_calendar_template_task_{name}"), TEMPLATE, type_="check")
    for column in (
        "source_reference",
        "growth_stage",
        "repeat_until_offset",
        "repeat_until_anchor",
        "repeat_every_days",
        "day_offset_end",
        "day_offset",
        "anchor",
    ):
        op.drop_column(TEMPLATE, column)
    # Templates seeded in Phase 7 have no week number; 0 keeps them loadable after a downgrade.
    op.add_column(
        TEMPLATE, sa.Column("week_no", sa.SmallInteger(), server_default="0", nullable=False)
    )
    op.alter_column(TEMPLATE, "week_no", server_default=None)

    growth_stage.drop(op.get_bind(), checkfirst=False)
    calendar_anchor.drop(op.get_bind(), checkfirst=False)
