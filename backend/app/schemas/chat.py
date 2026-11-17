from datetime import datetime

from pydantic import BaseModel

from app.models.enums import ChatSender


class ChatRequest(BaseModel):
    """POST /chat/messages. message is checked after trimming (1 to 500 characters), so its
    length errors use the documented codes rather than FastAPI's 422."""

    message: str
    session_id: int | None = None
    farm_id: int | None = None


class UserMessageOut(BaseModel):
    message_id: int
    message_text: str
    created_at: datetime


class ReplyOut(BaseModel):
    """intent_tag is null for the fallback; source_reference is null for the fallback and the
    farm-data answers."""

    message_id: int
    message_text: str
    intent_tag: str | None
    confidence: float | None
    source_reference: str | None
    created_at: datetime


class ChatExchange(BaseModel):
    session_id: int
    user_message: UserMessageOut
    reply: ReplyOut


class ChatSessionItem(BaseModel):
    session_id: int
    started_at: datetime
    last_message_at: datetime
    last_message_text: str


class ChatMessageItem(BaseModel):
    message_id: int
    sender: ChatSender
    message_text: str
    intent_tag: str | None
    confidence: float | None
    source_reference: str | None
    created_at: datetime
