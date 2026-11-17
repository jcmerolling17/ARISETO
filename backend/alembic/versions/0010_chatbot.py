"""Chatbot (Section 4 Tables 21-23): chat_intent, loaded from the team's intents.csv by
import-intents (nothing is seeded here), chat_session, and chat_message, where the bot's reply
carries the intent and confidence and the fallback has no intent.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

chat_sender = postgresql.ENUM("user", "bot", name="chat_sender", create_type=False)


def identity() -> sa.Identity:
    return sa.Identity(always=True)


def upgrade() -> None:
    chat_sender.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "chat_intent",
        sa.Column("intent_id", sa.Integer(), identity(), nullable=False),
        sa.Column("intent_tag", sa.String(80), nullable=False),
        sa.Column("crop_id", sa.SmallInteger(), nullable=True),
        sa.Column("response_en", sa.Text(), nullable=False),
        sa.Column("response_fil", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(
            ["crop_id"], ["crop.crop_id"], name=op.f("fk_chat_intent_crop_id_crop")
        ),
        sa.PrimaryKeyConstraint("intent_id", name=op.f("pk_chat_intent")),
        sa.UniqueConstraint("intent_tag", name=op.f("uq_chat_intent_intent_tag")),
    )

    op.create_table(
        "chat_session",
        sa.Column("session_id", sa.Integer(), identity(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.user_id"], name=op.f("fk_chat_session_user_id_users")
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_chat_session")),
    )
    op.create_index(op.f("ix_chat_session_user_id"), "chat_session", ["user_id"])

    op.create_table(
        "chat_message",
        sa.Column("message_id", sa.BigInteger(), identity(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("sender", chat_sender, nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("intent_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_chat_message_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_session.session_id"],
            name=op.f("fk_chat_message_session_id_chat_session"),
        ),
        sa.ForeignKeyConstraint(
            ["intent_id"],
            ["chat_intent.intent_id"],
            name=op.f("fk_chat_message_intent_id_chat_intent"),
        ),
        sa.PrimaryKeyConstraint("message_id", name=op.f("pk_chat_message")),
    )
    op.create_index(
        op.f("ix_chat_message_session_id_created_at"),
        "chat_message",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_message_session_id_created_at"), table_name="chat_message")
    op.drop_table("chat_message")
    op.drop_index(op.f("ix_chat_session_user_id"), table_name="chat_session")
    op.drop_table("chat_session")
    op.drop_table("chat_intent")
    chat_sender.drop(op.get_bind(), checkfirst=False)
