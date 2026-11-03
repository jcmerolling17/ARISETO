"""The weather alert rules (Section 6, "Weather alert rules (Phase 8)"): rule boundaries,
the 24-hour window, only the highest level per parameter, no repeats, and one notification
per active farm member. Forecasts are written straight into WEATHER_LOG."""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import cli
from app.models import AlertRule, Notification, User, WeatherAlert, WeatherLog
from app.models.enums import AccountStatus
from app.services import alert_service
from tests.conftest import WORKER_MOBILE

NOW = datetime(2026, 11, 3, 0, 0, tzinfo=UTC)
FETCHED = NOW - timedelta(minutes=10)
HOUR = timedelta(hours=1)


def _slot(farm_id: int, at: datetime, fetched_at: datetime = FETCHED, **values) -> WeatherLog:
    row = {
        "temp_c": Decimal("28"),
        "feels_like_c": None,
        "humidity_pct": 60,
        "rain_mm": Decimal("0"),
        "precip_probability_pct": 20,
        "wind_speed_mps": Decimal("2"),
        "condition_code": 500,
    }
    row.update(values)
    return WeatherLog(
        farm_id=farm_id, forecast_for=at, fetched_at=fetched_at, is_forecast=True, **row
    )


def _forecast(db, farm_id: int, start: datetime = NOW, fetched_at: datetime = FETCHED, **last):
    """Eight 3-hourly slots from start + 3 h to start + 24 h; the last one takes `last`."""
    slots = [
        _slot(farm_id, start + 3 * (i + 1) * HOUR, fetched_at, **(last if i == 7 else {}))
        for i in range(8)
    ]
    db.add_all(slots)
    db.commit()
    return slots


def _evaluate(db, farm_id: int, now: datetime = NOW) -> list[tuple[str, str]]:
    """(rule_name, message) of each alert issued by this evaluation."""
    alerts = alert_service.evaluate_farm(db, farm_id, now)
    db.commit()
    names = {rule.rule_id: rule.rule_name for rule in db.scalars(select(AlertRule))}
    return [(names[alert.rule_id], alert.message) for alert in alerts]


def _names(db, farm_id: int, now: datetime = NOW) -> list[str]:
    return [name for name, _ in _evaluate(db, farm_id, now)]


# ---------- Rain (sum) ----------


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        ("49.9", []),
        ("50", ["Heavy rain: PAGASA yellow level"]),
        ("99.99", ["Heavy rain: PAGASA yellow level"]),
        ("100", ["Heavy rain: PAGASA orange level"]),
        ("200", ["Heavy rain: PAGASA orange level"]),
        ("200.1", ["Heavy rain: PAGASA red level"]),
    ],
)
def test_rain_levels(db, farm, total: str, expected: list[str]) -> None:
    _forecast(db, farm.farm_id, rain_mm=Decimal(total))
    assert _names(db, farm.farm_id) == expected


def test_rain_adds_up_the_slots_in_the_window(db, farm) -> None:
    db.add_all(
        _slot(farm.farm_id, NOW + 3 * (i + 1) * HOUR, rain_mm=Decimal("6.25")) for i in range(8)
    )
    db.commit()

    assert _evaluate(db, farm.farm_id) == [
        (
            "Heavy rain: PAGASA yellow level",
            "Rain alert (PAGASA yellow level, 50 to 100 mm): about 50 mm of rain is forecast "
            "in the next 24 hours.",
        )
    ]


def test_message_value_rounds_half_up(db, farm) -> None:
    _forecast(db, farm.farm_id, rain_mm=Decimal("50.5"))
    [(_, message)] = _evaluate(db, farm.farm_id)
    assert "about 51 mm" in message


def test_alert_links_the_slot_with_the_highest_value_earliest_on_a_tie(db, farm) -> None:
    slots = [
        _slot(farm.farm_id, NOW + 3 * HOUR, rain_mm=Decimal("10")),
        _slot(farm.farm_id, NOW + 6 * HOUR, rain_mm=Decimal("20")),
        _slot(farm.farm_id, NOW + 9 * HOUR, rain_mm=Decimal("20")),
        _slot(farm.farm_id, NOW + 12 * HOUR, rain_mm=Decimal("5")),
    ]
    db.add_all(slots)
    db.commit()

    [alert] = alert_service.evaluate_farm(db, farm.farm_id, NOW)
    assert alert.weather_id == slots[1].weather_id
    assert alert.activity_id is None
    assert alert.severity == "info"
    assert alert.issued_at == NOW


# ---------- The window ----------


@pytest.mark.parametrize(
    ("offset", "fires"),
    [
        (timedelta(0), False),  # at the evaluation time: excluded
        (timedelta(seconds=1), True),
        (24 * HOUR, True),  # the end is included
        (24 * HOUR + timedelta(seconds=1), False),
    ],
)
def test_window_edges(db, farm, offset: timedelta, fires: bool) -> None:
    db.add(_slot(farm.farm_id, NOW + offset, rain_mm=Decimal("60")))
    db.commit()
    assert bool(_names(db, farm.farm_id)) is fires


def test_only_the_latest_fetch_counts(db, farm) -> None:
    older = FETCHED - 3 * HOUR
    # A slot left from an earlier fetch, still in the window, is ignored.
    db.add(_slot(farm.farm_id, NOW + 3 * HOUR, older, rain_mm=Decimal("60")))
    _forecast(db, farm.farm_id, rain_mm=Decimal("10"))
    assert _names(db, farm.farm_id) == []


def test_no_forecast_issues_nothing(db, farm) -> None:
    assert _names(db, farm.farm_id) == []


def test_current_readings_are_not_used(db, farm) -> None:
    reading = _slot(farm.farm_id, NOW + HOUR, rain_mm=Decimal("80"))
    reading.is_forecast = False
    db.add(reading)
    db.commit()
    assert _names(db, farm.farm_id) == []


# ---------- Wind and heat index (max) ----------


@pytest.mark.parametrize(("speed", "fires"), [("10.82", False), ("10.83", True)])
def test_strong_wind_boundary(db, farm, speed: str, fires: bool) -> None:
    _forecast(db, farm.farm_id, wind_speed_mps=Decimal(speed))
    assert _names(db, farm.farm_id) == (["Strong wind"] if fires else [])


def test_wind_message_is_in_km_h(db, farm) -> None:
    _forecast(db, farm.farm_id, wind_speed_mps=Decimal("10.83"))
    assert _evaluate(db, farm.farm_id) == [
        (
            "Strong wind",
            "Strong wind alert (PAGASA strong winds, 39 km/h and up): winds of up to 39 km/h "
            "are forecast in the next 24 hours.",
        )
    ]


def test_wind_takes_the_highest_slot_not_the_sum(db, farm) -> None:
    db.add_all(
        _slot(farm.farm_id, NOW + 3 * (i + 1) * HOUR, wind_speed_mps=Decimal("6")) for i in range(8)
    )
    db.commit()
    assert _names(db, farm.farm_id) == []


@pytest.mark.parametrize(
    ("temp_c", "humidity", "expected"),
    [
        ("35", 50, []),  # about 41 °C: Extreme Caution, which is off by default
        ("36", 55, ["Heat index: Danger"]),  # about 47 °C
        ("40", 60, ["Heat index: Extreme Danger"]),  # about 64 °C
    ],
)
def test_heat_index_levels(db, farm, temp_c: str, humidity: int, expected: list[str]) -> None:
    _forecast(db, farm.farm_id, temp_c=Decimal(temp_c), humidity_pct=humidity)
    assert _names(db, farm.farm_id) == expected


def test_heat_index_message(db, farm) -> None:
    _forecast(db, farm.farm_id, temp_c=Decimal("36"), humidity_pct=55)
    [(_, message)] = _evaluate(db, farm.farm_id)
    value = round(alert_service.heat_index_c(36, 55))
    assert message == (
        f"Heat index alert (PAGASA Danger, 42 to 51 °C): the heat index may reach {value} °C "
        "in the next 24 hours."
    )


@pytest.mark.parametrize(
    ("heat_index", "expected"),
    [
        (41.99, []),
        (42.0, ["Heat index: Danger"]),
        (51.99, ["Heat index: Danger"]),
        (52.0, ["Heat index: Extreme Danger"]),
    ],
)
def test_heat_index_thresholds(
    db, farm, monkeypatch: pytest.MonkeyPatch, heat_index: float, expected: list[str]
) -> None:
    # The given heat index on the slot at 30 °C, 30 °C on the others.
    monkeypatch.setattr(
        alert_service, "heat_index_c", lambda temp, _rh: heat_index if temp == 30 else 30.0
    )
    _forecast(db, farm.farm_id, temp_c=Decimal("30"))
    assert _names(db, farm.farm_id) == expected


def test_slots_without_temperature_or_humidity_are_skipped(db, farm) -> None:
    db.add_all(
        [
            _slot(farm.farm_id, NOW + 3 * HOUR, temp_c=None, humidity_pct=90),
            _slot(farm.farm_id, NOW + 6 * HOUR, temp_c=Decimal("40"), humidity_pct=None),
            _slot(farm.farm_id, NOW + 9 * HOUR, wind_speed_mps=None),
        ]
    )
    db.commit()
    assert _names(db, farm.farm_id) == []


def test_an_inactive_rule_never_fires(db, farm) -> None:
    db.scalar(select(AlertRule).where(AlertRule.rule_name == "Strong wind")).is_active = False
    db.commit()
    _forecast(db, farm.farm_id, wind_speed_mps=Decimal("15"))
    assert _names(db, farm.farm_id) == []


def test_extreme_caution_fires_once_turned_on(db, farm) -> None:
    rule = db.scalar(select(AlertRule).where(AlertRule.rule_name == "Heat index: Extreme Caution"))
    rule.is_active = True
    db.commit()
    _forecast(db, farm.farm_id, temp_c=Decimal("35"), humidity_pct=50)
    assert _names(db, farm.farm_id) == ["Heat index: Extreme Caution"]


def test_each_parameter_is_evaluated_on_its_own(db, farm) -> None:
    _forecast(
        db,
        farm.farm_id,
        rain_mm=Decimal("120"),
        wind_speed_mps=Decimal("12"),
        temp_c=Decimal("36"),
        humidity_pct=55,
    )
    assert _names(db, farm.farm_id) == [
        "Heavy rain: PAGASA orange level",
        "Heat index: Danger",
        "Strong wind",
    ]


# ---------- No repeats within 24 hours ----------


def _again(db, farm_id: int, hours: float, rain: str) -> list[str]:
    """A new fetch and evaluation `hours` after NOW."""
    now = NOW + timedelta(hours=hours)
    _forecast(db, farm_id, start=now, fetched_at=now - timedelta(minutes=5), rain_mm=Decimal(rain))
    return _names(db, farm_id, now)


def test_the_same_level_is_not_issued_again_within_24_hours(db, farm) -> None:
    _forecast(db, farm.farm_id, rain_mm=Decimal("60"))
    assert _names(db, farm.farm_id) == ["Heavy rain: PAGASA yellow level"]
    assert _again(db, farm.farm_id, 3, "70") == []
    assert _again(db, farm.farm_id, 23.9, "70") == []


def test_a_higher_level_is_issued_within_24_hours(db, farm) -> None:
    _forecast(db, farm.farm_id, rain_mm=Decimal("60"))
    assert _names(db, farm.farm_id) == ["Heavy rain: PAGASA yellow level"]
    assert _again(db, farm.farm_id, 3, "150") == ["Heavy rain: PAGASA orange level"]
    assert _again(db, farm.farm_id, 6, "250") == ["Heavy rain: PAGASA red level"]


def test_a_lower_level_is_not_issued_after_a_higher_one(db, farm) -> None:
    _forecast(db, farm.farm_id, rain_mm=Decimal("150"))
    assert _names(db, farm.farm_id) == ["Heavy rain: PAGASA orange level"]
    assert _again(db, farm.farm_id, 3, "60") == []


def test_the_level_can_be_issued_again_after_24_hours(db, farm) -> None:
    _forecast(db, farm.farm_id, rain_mm=Decimal("60"))
    assert _names(db, farm.farm_id) == ["Heavy rain: PAGASA yellow level"]
    assert _again(db, farm.farm_id, 24, "60") == ["Heavy rain: PAGASA yellow level"]


def test_no_repeat_is_per_parameter(db, farm) -> None:
    _forecast(db, farm.farm_id, rain_mm=Decimal("150"))
    assert _names(db, farm.farm_id) == ["Heavy rain: PAGASA orange level"]
    now = NOW + 3 * HOUR
    _forecast(db, farm.farm_id, start=now, fetched_at=now, wind_speed_mps=Decimal("12"))
    assert _names(db, farm.farm_id, now) == ["Strong wind"]


def test_no_repeat_is_per_farm(db, farm, other_farm) -> None:
    _forecast(db, farm.farm_id, rain_mm=Decimal("60"))
    _forecast(db, other_farm.farm_id, rain_mm=Decimal("60"))
    assert _names(db, farm.farm_id) == ["Heavy rain: PAGASA yellow level"]
    assert _names(db, other_farm.farm_id) == ["Heavy rain: PAGASA yellow level"]


# ---------- Notifications ----------


def _notifications(db) -> list[Notification]:
    return list(db.scalars(select(Notification).order_by(Notification.user_id)))


def _user_id(db, mobile_no: str) -> int:
    return db.scalar(select(User.user_id).where(User.mobile_no == mobile_no))


def test_one_notification_per_farm_member(db, farm, worker_token, outsider_token) -> None:
    _forecast(db, farm.farm_id, rain_mm=Decimal("60"))
    [alert] = alert_service.evaluate_farm(db, farm.farm_id, NOW)
    db.commit()

    rows = _notifications(db)
    owner_id = _user_id(db, "+639171234567")
    assert [row.user_id for row in rows] == [owner_id, _user_id(db, WORKER_MOBILE)]
    for row in rows:
        assert row.type == "weather_alert"
        assert row.alert_id == alert.alert_id
        assert row.farm_id == farm.farm_id
        assert row.title == "Heavy rain: PAGASA yellow level"
        assert row.body == alert.message
        assert row.severity == "info"
        assert row.created_at == NOW
        assert row.read_at is None


@pytest.mark.parametrize("status", [AccountStatus.DEACTIVATED, AccountStatus.PENDING])
def test_inactive_members_get_no_notification(db, farm, worker_token, status) -> None:
    db.get(User, _user_id(db, WORKER_MOBILE)).account_status = status
    db.commit()
    _forecast(db, farm.farm_id, rain_mm=Decimal("60"))
    alert_service.evaluate_farm(db, farm.farm_id, NOW)
    db.commit()

    assert [row.user_id for row in _notifications(db)] == [_user_id(db, "+639171234567")]


def test_nothing_issued_means_no_notifications(db, farm) -> None:
    _forecast(db, farm.farm_id, rain_mm=Decimal("10"))
    alert_service.evaluate_farm(db, farm.farm_id, NOW)
    db.commit()
    assert _notifications(db) == []
    assert db.scalars(select(WeatherAlert)).all() == []


# ---------- Running it ----------


def test_evaluate_after_fetch_never_raises(
    db, farm, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*_args, **_kwargs):
        raise RuntimeError("details that must not be logged")

    monkeypatch.setattr(alert_service, "evaluate_farm", broken)
    with caplog.at_level(logging.ERROR, logger="app.weather"):
        assert alert_service.evaluate_after_fetch(farm.farm_id) is None
    assert f"Alert evaluation failed for farm {farm.farm_id}: RuntimeError" in caplog.text
    assert "details" not in caplog.text


def test_unknown_farm_issues_nothing(db) -> None:
    assert alert_service.evaluate_farm(db, 999, NOW) == []


def test_cli_evaluates_every_farm(db, farm, other_farm, capsys) -> None:
    # Slots near the real time, since the command evaluates now.
    now = datetime.now(UTC)
    _forecast(db, farm.farm_id, start=now, fetched_at=now, rain_mm=Decimal("60"))

    assert cli.main(["evaluate-alerts"]) == 0
    assert "Alerts issued: 1 for 2 farms evaluated, 0 failed." in capsys.readouterr().out


def test_cli_evaluates_one_farm(db, farm, other_farm, capsys) -> None:
    now = datetime.now(UTC)
    _forecast(db, other_farm.farm_id, start=now, fetched_at=now, rain_mm=Decimal("60"))

    assert cli.main(["evaluate-alerts", "--farm-id", str(farm.farm_id)]) == 0
    assert "Alerts issued: 0 for 1 farms evaluated, 0 failed." in capsys.readouterr().out
    assert db.scalars(select(WeatherAlert)).all() == []


def test_cli_unknown_farm(db, capsys) -> None:
    assert cli.main(["evaluate-alerts", "--farm-id", "999"]) == 1
    assert "Farm 999 not found." in capsys.readouterr().err


def test_cli_reports_a_failed_farm(db, farm, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(alert_service, "evaluate_farm", broken)
    assert cli.main(["evaluate-alerts"]) == 1
    assert "0 for 0 farms evaluated, 1 failed." in capsys.readouterr().out
