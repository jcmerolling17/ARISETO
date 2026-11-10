"""weather_alert.weather_id becomes nullable with ON DELETE SET NULL. Each fetch replaces the
farm's future forecast slots, so an alert's triggering slot is deleted by the next fetch;
the alert, its message and its notifications stay, and only the link to the slot clears.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = "fk_weather_alert_weather_id_weather_log"


def upgrade() -> None:
    op.drop_constraint(op.f(FK), "weather_alert", type_="foreignkey")
    op.alter_column("weather_alert", "weather_id", existing_type=sa.BigInteger(), nullable=True)
    op.create_foreign_key(
        op.f(FK),
        "weather_alert",
        "weather_log",
        ["weather_id"],
        ["weather_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Alerts whose slot was replaced have no weather_id; NOT NULL can't hold them, so the
    # downgrade stops instead of deleting alerts.
    op.drop_constraint(op.f(FK), "weather_alert", type_="foreignkey")
    op.alter_column("weather_alert", "weather_id", existing_type=sa.BigInteger(), nullable=False)
    op.create_foreign_key(op.f(FK), "weather_alert", "weather_log", ["weather_id"], ["weather_id"])
