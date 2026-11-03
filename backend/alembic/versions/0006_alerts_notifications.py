"""Weather alerts and in-app notifications (Section 4 Tables 19, 20 and 24): alert_rule with
the seven seeded PAGASA rules (Section 6, "Weather alert rules (Phase 8)"), weather_alert,
and notification.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

task_type = postgresql.ENUM(name="task_type", create_type=False)
alert_parameter = postgresql.ENUM(
    "temp_c",
    "feels_like_c",
    "humidity_pct",
    "rain_mm",
    "precip_probability_pct",
    "wind_speed_mps",
    "heat_index_c",
    name="alert_parameter",
    create_type=False,
)
alert_operator = postgresql.ENUM(">", ">=", "<", "<=", name="alert_operator", create_type=False)
alert_severity = postgresql.ENUM(
    "info", "warning", "critical", name="alert_severity", create_type=False
)
alert_aggregation = postgresql.ENUM("sum", "max", name="alert_aggregation", create_type=False)
notification_type = postgresql.ENUM(
    "weather_alert",
    "task_reminder",
    "growth_stage",
    "yield_update",
    "disease_detected",
    name="notification_type",
    create_type=False,
)
NEW_TYPES = (alert_parameter, alert_operator, alert_severity, alert_aggregation, notification_type)

RAIN_MESSAGE = (
    "Rain alert (PAGASA {level}): about {{value}} mm of rain is forecast in the next "
    "{{hours}} hours."
)
HEAT_MESSAGE = (
    "Heat index alert (PAGASA {level}): the heat index may reach {{value}} °C in the next "
    "{{hours}} hours."
)


def _rule(name, parameter, aggregation, operator, threshold, severity, active, source, message):
    return {
        "rule_name": name,
        "parameter": parameter,
        "operator": operator,
        "threshold": threshold,
        "lookahead_hours": 24,
        "affected_task_type": None,
        "message_template": message,
        "severity": severity,
        "aggregation": aggregation,
        "source_reference": source,
        "is_active": active,
    }


# The seeded rules, in the documented order, all with a 24-hour window.
RULES = [
    _rule(
        "Heavy rain: PAGASA yellow level", "rain_mm", "sum", ">=", 50, "info", True,
        "PAGASA weather advisory: 50 to 100 mm in 24 hours",
        RAIN_MESSAGE.format(level="yellow level, 50 to 100 mm"),
    ),
    _rule(
        "Heavy rain: PAGASA orange level", "rain_mm", "sum", ">=", 100, "warning", True,
        "PAGASA weather advisory: 100 to 200 mm",
        RAIN_MESSAGE.format(level="orange level, 100 to 200 mm"),
    ),
    _rule(
        "Heavy rain: PAGASA red level", "rain_mm", "sum", ">", 200, "critical", True,
        "PAGASA weather advisory: more than 200 mm",
        RAIN_MESSAGE.format(level="red level, more than 200 mm"),
    ),
    _rule(
        "Heat index: Extreme Caution", "heat_index_c", "max", ">=", 33, "info", False,
        "PAGASA heat index classification: 33 to 41 °C",
        HEAT_MESSAGE.format(level="Extreme Caution, 33 to 41 °C"),
    ),
    _rule(
        "Heat index: Danger", "heat_index_c", "max", ">=", 42, "warning", True,
        "PAGASA heat index classification: 42 to 51 °C",
        HEAT_MESSAGE.format(level="Danger, 42 to 51 °C"),
    ),
    _rule(
        "Heat index: Extreme Danger", "heat_index_c", "max", ">=", 52, "critical", True,
        "PAGASA heat index classification: 52 °C and above",
        HEAT_MESSAGE.format(level="Extreme Danger, 52 °C and above"),
    ),
    _rule(
        "Strong wind", "wind_speed_mps", "max", ">=", 10.83, "warning", True,
        "PAGASA tropical cyclone wind signals: strong winds, 39 to 61 km/h "
        "(press release, 23 March 2022)",
        "Strong wind alert (PAGASA strong winds, 39 km/h and up): winds of up to {value} "
        "km/h are forecast in the next {hours} hours.",
    ),
]  # fmt: skip


def identity() -> sa.Identity:
    return sa.Identity(always=True)


def upgrade() -> None:
    for enum_type in NEW_TYPES:
        enum_type.create(op.get_bind(), checkfirst=False)

    alert_rule = op.create_table(
        "alert_rule",
        sa.Column("rule_id", sa.Integer(), identity(), nullable=False),
        sa.Column("rule_name", sa.String(100), nullable=False),
        sa.Column("parameter", alert_parameter, nullable=False),
        sa.Column("operator", alert_operator, nullable=False),
        sa.Column("threshold", sa.Numeric(6, 2), nullable=False),
        sa.Column("lookahead_hours", sa.SmallInteger(), nullable=False),
        sa.Column("affected_task_type", task_type, nullable=True),
        sa.Column("message_template", sa.Text(), nullable=False),
        sa.Column("severity", alert_severity, nullable=False),
        sa.Column("aggregation", alert_aggregation, nullable=False),
        sa.Column("source_reference", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("threshold > 0", name=op.f("ck_alert_rule_threshold_positive")),
        sa.CheckConstraint(
            "lookahead_hours > 0", name=op.f("ck_alert_rule_lookahead_hours_positive")
        ),
        sa.PrimaryKeyConstraint("rule_id", name=op.f("pk_alert_rule")),
    )
    op.bulk_insert(alert_rule, RULES)

    op.create_table(
        "weather_alert",
        sa.Column("alert_id", sa.BigInteger(), identity(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("farm_id", sa.Integer(), nullable=False),
        sa.Column("weather_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", alert_severity, nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["alert_rule.rule_id"], name=op.f("fk_weather_alert_rule_id_alert_rule")
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"], ["farm.farm_id"], name=op.f("fk_weather_alert_farm_id_farm")
        ),
        sa.ForeignKeyConstraint(
            ["weather_id"],
            ["weather_log.weather_id"],
            name=op.f("fk_weather_alert_weather_id_weather_log"),
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["crop_activity.activity_id"],
            name=op.f("fk_weather_alert_activity_id_crop_activity"),
        ),
        sa.PrimaryKeyConstraint("alert_id", name=op.f("pk_weather_alert")),
        sa.UniqueConstraint(
            "rule_id", "farm_id", "weather_id", name=op.f("uq_weather_alert_rule_id_farm_id_weather_id")
        ),
    )

    op.create_table(
        "notification",
        sa.Column("notification_id", sa.BigInteger(), identity(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("farm_id", sa.Integer(), nullable=True),
        sa.Column("alert_id", sa.BigInteger(), nullable=True),
        sa.Column("type", notification_type, nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("severity", alert_severity, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(type = 'weather_alert') = (alert_id IS NOT NULL)",
            name=op.f("ck_notification_alert_id_with_type"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.user_id"], name=op.f("fk_notification_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"], ["farm.farm_id"], name=op.f("fk_notification_farm_id_farm")
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["weather_alert.alert_id"],
            name=op.f("fk_notification_alert_id_weather_alert"),
        ),
        sa.PrimaryKeyConstraint("notification_id", name=op.f("pk_notification")),
        sa.UniqueConstraint(
            "user_id", "alert_id", name=op.f("uq_notification_user_id_alert_id")
        ),
    )
    op.create_index(
        op.f("ix_notification_user_id_created_at"), "notification", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_user_id_created_at"), table_name="notification")
    op.drop_table("notification")
    op.drop_table("weather_alert")
    op.drop_table("alert_rule")
    for enum_type in reversed(NEW_TYPES):
        enum_type.drop(op.get_bind(), checkfirst=False)
