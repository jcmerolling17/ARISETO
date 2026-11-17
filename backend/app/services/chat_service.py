"""The chatbot (DFD 6.1-6.4; Section 6, POST /chat/messages and the conversation history).

The question is classified by the intent model; at or above the threshold an active
CHAT_INTENT row answers, in Filipino when the member chose it and the text is filled in.
Below the threshold, or with no active row for the tag, the reply is the fallback. Two tags
are answered from the farm's own data. Both messages are saved in one transaction.
"""

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.seasons import philippine_today
from app.models import (
    ChatIntent,
    ChatMessage,
    ChatSession,
    CropActivity,
    CropCycle,
    Farm,
    FarmAssignment,
    FarmField,
    User,
    WeatherLog,
)
from app.models.enums import ActivityStatus, ChatSender, CycleStatus, LanguageCode
from app.schemas.chat import (
    ChatExchange,
    ChatMessageItem,
    ChatRequest,
    ChatSessionItem,
    ReplyOut,
    UserMessageOut,
)
from app.services.chat_model import Predictor

MAX_MESSAGE_LENGTH = 500
FALLBACK_TEXT = "Sorry, I didn't understand that. Try one of these topics:"
WEATHER_CHECK = "weather_check"
TODAY_TASKS = "today_tasks"
FARM_DATA_TAGS = frozenset({WEATHER_CHECK, TODAY_TASKS})
TASKS_SHOWN = 5
WEATHER_WINDOW = timedelta(hours=24)


def _half_up(value: Decimal, places: str = "1") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


# ---------- Farm-data answers ----------


def weather_answer(db: Session, farm: Farm, now: datetime) -> str | None:
    """ "{farm_name}: {temp_c}°C now. Next 24 hours: up to {pop}% chance of rain, about
    {rain_mm} mm." from stored weather only; None when the current reading or the forecast
    slots after now (up to 24 hours ahead) are missing."""
    current = db.scalar(
        select(WeatherLog)
        .where(WeatherLog.farm_id == farm.farm_id, WeatherLog.is_forecast.is_(False))
        .order_by(WeatherLog.forecast_for.desc(), WeatherLog.fetched_at.desc())
        .limit(1)
    )
    slots = db.scalars(
        select(WeatherLog).where(
            WeatherLog.farm_id == farm.farm_id,
            WeatherLog.is_forecast.is_(True),
            WeatherLog.forecast_for > now,
            WeatherLog.forecast_for <= now + WEATHER_WINDOW,
        )
    ).all()
    chances = [s.precip_probability_pct for s in slots if s.precip_probability_pct is not None]
    if current is None or current.temp_c is None or not slots or not chances:
        return None
    rain = sum((s.rain_mm for s in slots if s.rain_mm is not None), Decimal(0))
    return (
        f"{farm.farm_name}: {_half_up(Decimal(current.temp_c))}°C now. Next 24 hours: up to "
        f"{_half_up(Decimal(max(chances)))}% chance of rain, about "
        f"{_half_up(Decimal(rain), '0.1')} mm."
    )


def tasks_answer(db: Session, farm: Farm, now: datetime) -> str:
    """Today's pending and rescheduled tasks on the farm's planned and active cycles, in
    calendar order: "Today on {farm_name}: {title} ({field_name}); …", at most five, then
    "and N more"; or "No tasks are due today on {farm_name}."."""
    rows = db.execute(
        select(CropActivity.title, FarmField.field_name)
        .join(CropCycle, CropCycle.cycle_id == CropActivity.cycle_id)
        .join(FarmField, FarmField.field_id == CropCycle.field_id)
        .where(
            FarmField.farm_id == farm.farm_id,
            CropCycle.status.in_([CycleStatus.PLANNED, CycleStatus.ACTIVE]),
            CropActivity.status.in_([ActivityStatus.PENDING, ActivityStatus.RESCHEDULED]),
            CropActivity.scheduled_date == philippine_today(now),
        )
        .order_by(CropActivity.scheduled_time.asc().nulls_last(), CropActivity.activity_id)
    ).all()
    if not rows:
        return f"No tasks are due today on {farm.farm_name}."
    listed = "; ".join(f"{title} ({field})" for title, field in rows[:TASKS_SHOWN])
    more = len(rows) - TASKS_SHOWN
    return f"Today on {farm.farm_name}: {listed}" + (f" and {more} more." if more > 0 else ".")


# ---------- Sending a message ----------


def _check_message(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise AppError(422, "message_empty")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise AppError(422, "message_too_long")
    return text


def _farm_for(db: Session, user: User, farm_id: int | None) -> Farm | None:
    """The farm used for farm-data answers: farm_id (403 not_farm_member unless the caller
    belongs to it), or the caller's only farm, or none."""
    if farm_id is not None:
        member = db.scalar(
            select(FarmAssignment.assignment_id).where(
                FarmAssignment.farm_id == farm_id, FarmAssignment.user_id == user.user_id
            )
        )
        if member is None:
            raise AppError(403, "not_farm_member")
        return db.get(Farm, farm_id)
    farm_ids = db.scalars(
        select(FarmAssignment.farm_id).where(FarmAssignment.user_id == user.user_id).limit(2)
    ).all()
    return db.get(Farm, farm_ids[0]) if len(farm_ids) == 1 else None


def _own_session(db: Session, user: User, session_id: int) -> ChatSession:
    """The caller's conversation; 404 session_not_found otherwise, also for another user's."""
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user.user_id:
        raise AppError(404, "session_not_found")
    return session


def _localized(user: User, intent: ChatIntent) -> str:
    if user.preferred_language == LanguageCode.FIL and (intent.response_fil or "").strip():
        return intent.response_fil
    return intent.response_en


def _source(intent: ChatIntent | None) -> str | None:
    """The guide behind an intent's answer; none for the fallback and the farm-data intents."""
    if intent is None or intent.intent_tag in FARM_DATA_TAGS:
        return None
    return intent.source_reference


def _answer(db: Session, user: User, intent: ChatIntent, farm: Farm | None, now) -> str:
    """The farm-data answer for weather_check and today_tasks when there is a farm (and stored
    weather); otherwise the intent's fixed response."""
    if farm is not None and intent.intent_tag == WEATHER_CHECK:
        answer = weather_answer(db, farm, now)
        if answer is not None:
            return answer
    if farm is not None and intent.intent_tag == TODAY_TASKS:
        return tasks_answer(db, farm, now)
    return _localized(user, intent)


def send_message(
    db: Session,
    user: User,
    predictor: Predictor,
    data: ChatRequest,
    now: datetime | None = None,
) -> ChatExchange:
    """Answer a question and save both messages (DFD 6.4).

    Errors: 403 not_farm_member; 404 session_not_found; 422 message_empty, message_too_long.
    """
    now = now or datetime.now(UTC)
    text = _check_message(data.message)
    farm = _farm_for(db, user, data.farm_id)
    session = _own_session(db, user, data.session_id) if data.session_id is not None else None

    prediction = predictor.predict(text)
    intent = None
    if prediction.confidence >= predictor.threshold:
        intent = db.scalar(
            select(ChatIntent).where(
                ChatIntent.intent_tag == prediction.label, ChatIntent.is_active.is_(True)
            )
        )
    reply_text = FALLBACK_TEXT if intent is None else _answer(db, user, intent, farm, now)

    try:
        if session is None:
            session = ChatSession(user_id=user.user_id)
            db.add(session)
            db.flush()
        question = ChatMessage(
            session_id=session.session_id, sender=ChatSender.USER, message_text=text
        )
        reply = ChatMessage(
            session_id=session.session_id,
            sender=ChatSender.BOT,
            message_text=reply_text,
            intent_id=intent.intent_id if intent else None,
            confidence=Decimal(str(round(prediction.confidence, 4))),
        )
        db.add_all([question, reply])
        db.commit()
    except BaseException:
        db.rollback()
        raise
    db.refresh(question)
    db.refresh(reply)
    return ChatExchange(
        session_id=session.session_id,
        user_message=UserMessageOut(
            message_id=question.message_id,
            message_text=question.message_text,
            created_at=question.created_at,
        ),
        reply=ReplyOut(
            message_id=reply.message_id,
            message_text=reply.message_text,
            intent_tag=intent.intent_tag if intent else None,
            confidence=float(reply.confidence),
            source_reference=_source(intent),
            created_at=reply.created_at,
        ),
    )


# ---------- History ----------


def list_sessions(db: Session, user: User, limit: int) -> list[ChatSessionItem]:
    """The caller's conversations, latest activity first."""
    last = (
        select(ChatMessage.session_id, func.max(ChatMessage.message_id).label("message_id"))
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    rows = db.execute(
        select(ChatSession, ChatMessage)
        .join(last, last.c.session_id == ChatSession.session_id)
        .join(ChatMessage, ChatMessage.message_id == last.c.message_id)
        .where(ChatSession.user_id == user.user_id)
        .order_by(ChatMessage.created_at.desc(), ChatSession.session_id.desc())
        .limit(limit)
    )
    return [
        ChatSessionItem(
            session_id=session.session_id,
            started_at=session.started_at,
            last_message_at=message.created_at,
            last_message_text=message.message_text,
        )
        for session, message in rows
    ]


def list_messages(
    db: Session, user: User, session_id: int, limit: int, offset: int
) -> list[ChatMessageItem]:
    """A conversation's messages, oldest first. Errors: 404 session_not_found."""
    _own_session(db, user, session_id)
    rows = db.execute(
        select(ChatMessage, ChatIntent)
        .outerjoin(ChatIntent, ChatIntent.intent_id == ChatMessage.intent_id)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at, ChatMessage.message_id)
        .limit(limit)
        .offset(offset)
    )
    return [
        ChatMessageItem(
            message_id=message.message_id,
            sender=message.sender,
            message_text=message.message_text,
            intent_tag=intent.intent_tag if intent else None,
            confidence=float(message.confidence) if message.confidence is not None else None,
            source_reference=_source(intent),
            created_at=message.created_at,
        )
        for message, intent in rows
    ]
