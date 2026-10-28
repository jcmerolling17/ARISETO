"""Account settings columns on users: terms_accepted_at, deletion_requested_at, and
password_changed_at (Section 4). All three are nullable, so existing accounts keep NULL.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("terms_accepted_at", "deletion_requested_at", "password_changed_at")


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("users", sa.Column(column, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("users", column)
