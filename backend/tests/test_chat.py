"""POST /chat/messages and the conversation history (Section 6; DFD 6.2-6.4) with a fake
predictor: the threshold, the fallback, language, the farm-data answers, the farm choice,
session ownership, and paging.

Intents here are made-up test rows (tags test_*), not the team's knowledge base."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.v1.endpoints.chat import get_chat_predictor
from app.core.seasons import philippine_today
from app.main import app
from app.models import (
    ChatIntent,
    ChatMessage,
    ChatSession,
    CropActivity,
    CropCycle,
    User,
    WeatherLog,
)
from app.models.enums import ActivityStatus, CycleStatus, LanguageCode
from app.services.disease_model import Prediction
from tests.conftest import FarmSetup, auth_header, create_farm

URL = "/api/v1/chat/messages"
THRESHOLD = 0.7
FALLBACK = "Sorry, I didn't understand that. Try one of these topics:"


@dataclass
class FakePredictor:
    label: str = "test_greeting"
    confidence: float = 0.9
    version: str = "test-1.0"
    threshold: float = THRESHOLD
    seen: list[str] = field(default_factory=list)

    def predict(self, text: str) -> Prediction:
        self.seen.append(text)
        return Prediction(self.label, self.confidence)


@pytest.fixture
def predictor() -> FakePredictor:
    fake = FakePredictor()
    app.dependency_overrides[get_chat_predictor] = lambda: fake
    return fake


def add_intent(db, tag, *, en=None, fil=None, source="Test guide", active=True) -> ChatIntent:
    intent = ChatIntent(
        intent_tag=tag,
        response_en=en or f"English answer for {tag}",
        response_fil=fil,
        source_reference=source,
        is_active=active,
    )
    db.add(intent)
    db.commit()
    return intent


@pytest.fixture
def intents(db) -> None:
    add_intent(db, "test_greeting", fil="Sagot sa Filipino")
    add_intent(db, "weather_check", en="Fixed weather answer", source=None)
    add_intent(db, "today_tasks", en="Fixed tasks answer", source=None)


def ask(client, token, message="Hello there", **extra):
    return client.post(URL, json={"message": message, **extra}, headers=auth_header(token))


def set_language(db, mobile: str, language: LanguageCode) -> None:
    user = db.scalar(select(User).where(User.mobile_no == mobile))
    user.preferred_language = language
    db.commit()


def message_count(db) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(ChatMessage))


# ---------- Model and checks ----------


def test_no_model_is_503_and_saves_nothing(client, member_token, db) -> None:
    response = ask(client, member_token, "   ")  # 503 comes before the message checks

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "model_unavailable"}}
    assert message_count(db) == 0
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 0


def test_api_starts_without_a_model_and_logs_one_warning(caplog) -> None:
    with caplog.at_level("WARNING", logger="app.chat"), TestClient(app):
        pass
    warnings = [r for r in caplog.records if r.name == "app.chat"]
    assert len(warnings) == 1
    assert "Chatbot is off: not configured" in warnings[0].getMessage()


@pytest.mark.parametrize(
    ("message", "code"),
    [("", "message_empty"), ("   \n ", "message_empty"), ("x" * 501, "message_too_long")],
)
def test_message_length(client, member_token, predictor, db, message, code) -> None:
    response = ask(client, member_token, message)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": code}}
    assert message_count(db) == 0


def test_message_is_trimmed_not_collapsed(client, member_token, predictor, intents) -> None:
    response = ask(client, member_token, "  " + "a  b" + "x" * 496 + "  ")

    assert response.status_code == 201
    assert response.json()["user_message"]["message_text"] == "a  b" + "x" * 496
    assert predictor.seen == ["a  b" + "x" * 496]


# ---------- Answers ----------


def test_answer_from_the_intent(client, member_token, predictor, intents, db) -> None:
    set_language(db, "+639171234567", LanguageCode.EN)

    response = ask(client, member_token)

    assert response.status_code == 201
    body = response.json()
    assert body["user_message"]["message_text"] == "Hello there"
    assert body["reply"]["message_text"] == "English answer for test_greeting"
    assert body["reply"]["intent_tag"] == "test_greeting"
    assert body["reply"]["confidence"] == 0.9
    assert body["reply"]["source_reference"] == "Test guide"

    db.expire_all()
    question, reply = db.scalars(select(ChatMessage).order_by(ChatMessage.message_id)).all()
    assert (question.sender, question.intent_id, question.confidence) == ("user", None, None)
    assert reply.sender == "bot"
    assert reply.intent_id is not None
    assert reply.confidence == Decimal("0.9000")


@pytest.mark.parametrize(
    ("label", "confidence", "fallback"),
    [
        ("test_greeting", 0.6999, True),  # below the threshold
        ("test_greeting", THRESHOLD, False),  # equal passes
        ("test_inactive", 0.95, True),  # inactive intent
        ("test_no_row", 0.95, True),  # label with no CHAT_INTENT row
    ],
)
def test_fallback_rules(
    client, member_token, predictor, intents, db, label, confidence, fallback
) -> None:
    add_intent(db, "test_inactive", active=False)
    predictor.label, predictor.confidence = label, confidence

    body = ask(client, member_token).json()

    if fallback:
        assert body["reply"]["message_text"] == FALLBACK
        assert body["reply"]["intent_tag"] is None
        assert body["reply"]["source_reference"] is None
        assert body["reply"]["confidence"] == confidence
        db.expire_all()
        reply = db.scalar(select(ChatMessage).where(ChatMessage.sender == "bot"))
        assert reply.intent_id is None
    else:
        assert body["reply"]["intent_tag"] == label


@pytest.mark.parametrize(
    ("language", "fil", "expected"),
    [
        (LanguageCode.FIL, "Sagot sa Filipino", "Sagot sa Filipino"),
        (LanguageCode.FIL, "   ", "English answer for test_filipino"),
        (LanguageCode.FIL, None, "English answer for test_filipino"),
        (LanguageCode.EN, "Sagot sa Filipino", "English answer for test_filipino"),
    ],
)
def test_language(client, member_token, predictor, db, language, fil, expected) -> None:
    add_intent(db, "test_filipino", fil=fil)
    set_language(db, "+639171234567", language)
    predictor.label = "test_filipino"

    assert ask(client, member_token).json()["reply"]["message_text"] == expected


# ---------- Farm data ----------


def weather_row(farm_id, forecast_for, *, is_forecast, temp=None, pop=None, rain=None):
    return WeatherLog(
        farm_id=farm_id,
        forecast_for=forecast_for,
        fetched_at=datetime.now(UTC),
        temp_c=temp,
        precip_probability_pct=pop,
        rain_mm=rain,
        condition_code=800,
        is_forecast=is_forecast,
    )


def test_weather_check_from_stored_weather(
    client, member_token, predictor, intents, farm: FarmSetup, db
) -> None:
    now = datetime.now(UTC)
    db.add_all(
        [
            weather_row(
                farm.farm_id, now - timedelta(hours=5), is_forecast=False, temp=Decimal("28.4")
            ),
            weather_row(
                farm.farm_id, now - timedelta(hours=1), is_forecast=False, temp=Decimal("31.5")
            ),
            weather_row(
                farm.farm_id,
                now + timedelta(hours=3),
                is_forecast=True,
                pop=40,
                rain=Decimal("12.25"),
            ),
            weather_row(
                farm.farm_id,
                now + timedelta(hours=6),
                is_forecast=True,
                pop=80,
                rain=Decimal("0.10"),
            ),
            weather_row(
                farm.farm_id, now + timedelta(hours=9), is_forecast=True, pop=None, rain=None
            ),
            # Outside the next 24 hours: left out.
            weather_row(
                farm.farm_id,
                now - timedelta(hours=2),
                is_forecast=True,
                pop=100,
                rain=Decimal("50"),
            ),
            weather_row(
                farm.farm_id,
                now + timedelta(hours=27),
                is_forecast=True,
                pop=100,
                rain=Decimal("50"),
            ),
        ]
    )
    db.commit()
    predictor.label = "weather_check"

    reply = ask(client, member_token, farm_id=farm.farm_id).json()["reply"]

    assert reply["message_text"] == (
        "MPMPC Farm: 32°C now. Next 24 hours: up to 80% chance of rain, about 12.4 mm."
    )
    assert reply["intent_tag"] == "weather_check"
    assert reply["source_reference"] is None


@pytest.mark.parametrize("missing", ["current", "slots"])
def test_weather_check_without_stored_weather_sends_the_fixed_response(
    client, member_token, predictor, intents, farm: FarmSetup, db, missing
) -> None:
    now = datetime.now(UTC)
    if missing != "current":
        db.add(weather_row(farm.farm_id, now, is_forecast=False, temp=Decimal("30")))
    if missing != "slots":
        db.add(
            weather_row(farm.farm_id, now + timedelta(hours=3), is_forecast=True, pop=10, rain=0)
        )
    db.commit()
    predictor.label = "weather_check"

    reply = ask(client, member_token, farm_id=farm.farm_id).json()["reply"]

    assert reply["message_text"] == "Fixed weather answer"
    assert reply["source_reference"] is None


def add_task(db, cycle_id, title, *, day=None, at=None, status=ActivityStatus.PENDING):
    db.add(
        CropActivity(
            cycle_id=cycle_id,
            title=title,
            scheduled_date=day or philippine_today(),
            scheduled_time=at,
            status=status,
            client_uuid=uuid.uuid4(),
        )
    )
    db.commit()


def test_today_tasks_none(client, member_token, predictor, intents, farm: FarmSetup) -> None:
    predictor.label = "today_tasks"

    reply = ask(client, member_token, farm_id=farm.farm_id).json()["reply"]

    assert reply["message_text"] == "No tasks are due today on MPMPC Farm."
    assert reply["source_reference"] is None


def test_today_tasks_in_calendar_order(
    client, member_token, predictor, intents, farm: FarmSetup, db
) -> None:
    a, b = farm.cycle_ids["Field A"], farm.cycle_ids["Field B"]
    add_task(db, a, "No time")
    add_task(db, b, "Late", at=time(15, 0))
    add_task(db, a, "Early", at=time(6, 30))
    add_task(db, b, "Moved", status=ActivityStatus.RESCHEDULED)
    # Left out: done, skipped, another day.
    add_task(db, a, "Finished", status=ActivityStatus.DONE)
    add_task(db, a, "Skipped", status=ActivityStatus.SKIPPED)
    add_task(db, a, "Tomorrow", day=philippine_today() + timedelta(days=1))
    predictor.label = "today_tasks"

    reply = ask(client, member_token, farm_id=farm.farm_id).json()["reply"]

    assert reply["message_text"] == (
        "Today on MPMPC Farm: Early (Field A); Late (Field B); No time (Field A); Moved (Field B)."
    )


def test_today_tasks_more_than_five(
    client, member_token, predictor, intents, farm: FarmSetup, db
) -> None:
    for n in range(1, 8):
        add_task(db, farm.cycle_ids["Field A"], f"T{n}", at=time(6, n))
    predictor.label = "today_tasks"

    reply = ask(client, member_token).json()["reply"]  # the only farm, without farm_id

    assert reply["message_text"] == (
        "Today on MPMPC Farm: T1 (Field A); T2 (Field A); T3 (Field A); T4 (Field A); "
        "T5 (Field A) and 2 more."
    )


def test_today_tasks_skip_closed_cycles(
    client, member_token, predictor, intents, farm: FarmSetup, db
) -> None:
    add_task(db, farm.cycle_ids["Field A"], "On a harvested cycle")
    db.get(CropCycle, farm.cycle_ids["Field A"]).status = CycleStatus.HARVESTED
    db.commit()
    predictor.label = "today_tasks"

    reply = ask(client, member_token, farm_id=farm.farm_id).json()["reply"]

    assert reply["message_text"] == "No tasks are due today on MPMPC Farm."


def test_farm_data_without_a_farm_sends_the_fixed_response(
    client, member_token, predictor, intents
) -> None:
    for tag, fixed in (
        ("weather_check", "Fixed weather answer"),
        ("today_tasks", "Fixed tasks answer"),
    ):
        predictor.label = tag
        assert ask(client, member_token).json()["reply"]["message_text"] == fixed


def test_two_farms_without_farm_id_send_the_fixed_response(
    client, member_token, predictor, intents, farm: FarmSetup, barangay_id, variety_ids
) -> None:
    create_farm(client, member_token, barangay_id, variety_ids, philippine_today())
    predictor.label = "today_tasks"

    assert ask(client, member_token).json()["reply"]["message_text"] == "Fixed tasks answer"


def test_worker_can_use_the_farm(client, worker_token, predictor, intents, farm: FarmSetup) -> None:
    predictor.label = "today_tasks"

    reply = ask(client, worker_token, farm_id=farm.farm_id).json()["reply"]

    assert reply["message_text"] == "No tasks are due today on MPMPC Farm."


def test_farm_of_someone_else_is_403(
    client, outsider_token, predictor, intents, farm: FarmSetup, db
) -> None:
    for farm_id in (farm.farm_id, 99999):
        response = ask(client, outsider_token, farm_id=farm_id)
        assert response.status_code == 403
        assert response.json() == {"detail": {"code": "not_farm_member"}}
    assert message_count(db) == 0


# ---------- Sessions and history ----------


def test_new_session_then_continue_it(client, member_token, predictor, intents, db) -> None:
    first = ask(client, member_token).json()
    second = ask(client, member_token, "Again", session_id=first["session_id"]).json()
    third = ask(client, member_token, "New one").json()

    assert second["session_id"] == first["session_id"]
    assert third["session_id"] != first["session_id"]
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 2


def test_someone_elses_session_is_404(
    client, member_token, worker_token, predictor, intents, db
) -> None:
    session_id = ask(client, member_token).json()["session_id"]

    for token, sid in ((worker_token, session_id), (member_token, 99999)):
        response = ask(client, token, session_id=sid)
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "session_not_found"}}
    history = client.get(
        f"/api/v1/chat/sessions/{session_id}/messages", headers=auth_header(worker_token)
    )
    assert history.status_code == 404
    assert history.json() == {"detail": {"code": "session_not_found"}}
    assert client.get("/api/v1/chat/sessions", headers=auth_header(worker_token)).json() == []


def test_sessions_latest_activity_first(client, member_token, predictor, intents) -> None:
    older = ask(client, member_token, "First chat").json()["session_id"]
    newer = ask(client, member_token, "Second chat").json()["session_id"]
    ask(client, member_token, "Back to the first", session_id=older)

    listed = client.get("/api/v1/chat/sessions", headers=auth_header(member_token)).json()
    limited = client.get("/api/v1/chat/sessions?limit=1", headers=auth_header(member_token)).json()

    assert [s["session_id"] for s in listed] == [older, newer]
    assert listed[0]["last_message_text"] == "Sagot sa Filipino"  # the test member reads Filipino
    assert [s["session_id"] for s in limited] == [older]


def test_history_oldest_first_with_sources_and_paging(
    client, member_token, predictor, intents, db
) -> None:
    set_language(db, "+639171234567", LanguageCode.EN)
    session_id = ask(client, member_token, "Hello").json()["session_id"]
    predictor.confidence = 0.1
    ask(client, member_token, "Gibberish", session_id=session_id)
    url = f"/api/v1/chat/sessions/{session_id}/messages"

    history = client.get(url, headers=auth_header(member_token)).json()
    page = client.get(f"{url}?limit=2&offset=1", headers=auth_header(member_token)).json()

    assert [(m["sender"], m["message_text"]) for m in history] == [
        ("user", "Hello"),
        ("bot", "English answer for test_greeting"),
        ("user", "Gibberish"),
        ("bot", FALLBACK),
    ]
    assert history[0]["intent_tag"] is None and history[0]["confidence"] is None
    assert history[1]["source_reference"] == "Test guide"
    assert history[1]["intent_tag"] == "test_greeting"
    assert history[3]["intent_tag"] is None and history[3]["source_reference"] is None
    assert history[3]["confidence"] == 0.1
    assert [m["message_text"] for m in page] == ["English answer for test_greeting", "Gibberish"]


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
def test_history_paging_limits(client, member_token, predictor, intents, query) -> None:
    session_id = ask(client, member_token).json()["session_id"]

    response = client.get(
        f"/api/v1/chat/sessions/{session_id}/messages?{query}", headers=auth_header(member_token)
    )

    assert response.status_code == 422


@pytest.mark.parametrize("query", ["limit=0", "limit=51"])
def test_sessions_limit(client, member_token, query) -> None:
    response = client.get(f"/api/v1/chat/sessions?{query}", headers=auth_header(member_token))

    assert response.status_code == 422
