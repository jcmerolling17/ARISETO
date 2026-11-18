"""Account deletion (Phase 13): a processed deletion request replaces the member's mobile
number with D<user_id>, which no sign-up or profile change can ever enter, so the users
mobile_no check also accepts that form. No column is added.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOBILE = r"mobile_no ~ '^\+639[0-9]{9}$'"
DELETED = r"mobile_no ~ '^D[0-9]{1,10}$'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_users_mobile_no_format"), "users", type_="check")
    op.create_check_constraint("mobile_no_format", "users", f"{MOBILE} OR {DELETED}")


def downgrade() -> None:
    # Refuses to run while processed accounts exist, since their D<user_id> would break it.
    op.drop_constraint(op.f("ck_users_mobile_no_format"), "users", type_="check")
    op.create_check_constraint("mobile_no_format", "users", MOBILE)
