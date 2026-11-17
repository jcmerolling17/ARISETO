from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ChatSender, chat_sender


class ChatIntent(Base):
    """CHAT_INTENT (Table 23): one intent the Keras model can name, with its answers. Loaded
    from the team's intents.csv by import-intents; intent_tag matches a model label."""

    __tablename__ = "chat_intent"

    intent_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    intent_tag: Mapped[str] = mapped_column(String(80), unique=True)
    crop_id: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey("crop.crop_id"))
    response_en: Mapped[str] = mapped_column(Text)
    response_fil: Mapped[str | None] = mapped_column(Text)
    # Required except for the farm-data intents (weather_check, today_tasks); kept by the import.
    source_reference: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class ChatSession(Base):
    """CHAT_SESSION (Table 21): one conversation of one member."""

    __tablename__ = "chat_session"

    session_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(Base):
    """CHAT_MESSAGE (Table 22): a question or a reply. intent_id and confidence are set on the
    bot's reply; intent_id is NULL for the fallback and on the member's own messages."""

    __tablename__ = "chat_message"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        Index("ix_chat_message_session_id_created_at", "session_id", "created_at"),
    )

    message_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_session.session_id"))
    sender: Mapped[ChatSender] = mapped_column(chat_sender)
    message_text: Mapped[str] = mapped_column(Text)
    intent_id: Mapped[int | None] = mapped_column(ForeignKey("chat_intent.intent_id"))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
