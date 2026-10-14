"""Saving fetches in WEATHER_LOG, fetching farms, the fetch after farm setup, and the
fetch-weather command. OpenWeatherMap is always an httpx2 MockTransport with a fake key."""

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app import cli
from app.core.config import get_settings
from app.models import Farm, WeatherLog
from app.services import openweathermap_service, weather_fetch_service
from app.services.openweathermap_service import FetchedWeather
from tests.conftest import auth_header

KEY = "test-key-not-real"


def _ts(moment: datetime) -> int:
    return int(moment.timestamp())


def _owm_handler(now: datetime, failing_lat: str | None = None, requests: list | None = None):
    """Made-up OpenWeatherMap answers: a current reading 10 minutes ago and three slots,
    3, 6 and 9 hours from now. Requests for failing_lat get HTTP 500."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if requests is not None:
            requests.append(request)
        if request.url.params["lat"] == failing_lat:
            return httpx2.Response(500, json={"message": "server error"})
        if request.url.path.endswith("/weather"):
            return httpx2.Response(
                200,
                json={
                    "dt": _ts(now - timedelta(minutes=10)),
                    "weather": [{"id": 801}],
                    "main": {"temp": 28.5, "feels_like": 31.0, "humidity": 80},
                    "wind": {"speed": 2.5},
                },
            )
        slots = [
            {
                "dt": _ts(now + timedelta(hours=hours)),
                "weather": [{"id": 500}],
                "main": {"temp": 27 + hours / 3, "feels_like": 30, "humidity": 82},
                "wind": {"speed": 3},
                "rain": {"3h": 0.5},
                "pop": 0.4,
            }
            for hours in (3, 6, 9)
        ]
        return httpx2.Response(200, json={"list": slots})

    return handler


@pytest.fixture
def fake_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "openweathermap_api_key", SecretStr(KEY))


def _mock_client(now: datetime, **kwargs) -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(_owm_handler(now, **kwargs)))


def _setup_body(barangay_id: int, variety_ids, name: str = "MPMPC Farm") -> dict:
    return {
        "farm_name": name,
        "barangay_id": barangay_id,
        "season": "wet",
        "fields": [
            {
                "field_name": "Field A",
                "area_ha": 1.25,
                "variety_id": variety_ids["NK6410"],
                "planting_date": date.today().isoformat(),
            }
        ],
    }


@pytest.fixture
def two_farms(
    client: TestClient, member_token: str, barangay_id: int, variety_ids, db
) -> list[int]:
    """Two farms; the second is moved so its weather requests can be told apart."""
    ids = [
        client.post(
            "/api/v1/farms",
            json=_setup_body(barangay_id, variety_ids, name),
            headers=auth_header(member_token),
        ).json()["farm_id"]
        for name in ("First Farm", "Second Farm")
    ]
    db.get(Farm, ids[1]).latitude = Decimal("12.5")
    db.commit()
    return ids


def _rows(db, farm_id: int, is_forecast: bool) -> list[WeatherLog]:
    return db.scalars(
        select(WeatherLog)
        .where(WeatherLog.farm_id == farm_id, WeatherLog.is_forecast.is_(is_forecast))
        .order_by(WeatherLog.forecast_for)
    ).all()


def _fetched(fetched_at: datetime, slot_times: list[datetime], temp: str) -> FetchedWeather:
    def row(at: datetime, is_forecast: bool) -> dict:
        return {
            "forecast_for": at,
            "temp_c": Decimal(temp),
            "feels_like_c": None,
            "humidity_pct": None,
            "rain_mm": Decimal("0"),
            "precip_probability_pct": None,
            "wind_speed_mps": None,
            "condition_code": 800,
            "is_forecast": is_forecast,
            "fetched_at": fetched_at,
        }

    return FetchedWeather(
        current=row(fetched_at - timedelta(minutes=5), False),
        forecast=[row(at, True) for at in slot_times],
    )


def test_a_fetch_keeps_current_readings_and_replaces_future_slots(db, two_farms) -> None:
    farm_id = two_farms[0]
    first = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)
    second = first + timedelta(hours=4)
    hour = timedelta(hours=1)
    weather_fetch_service.save_fetch(
        db, farm_id, _fetched(first, [first + 3 * hour, first + 6 * hour, first + 9 * hour], "27")
    )
    db.commit()

    weather_fetch_service.save_fetch(
        db, farm_id, _fetched(second, [first + 6 * hour, first + 9 * hour], "30")
    )
    db.commit()

    assert [r.fetched_at for r in _rows(db, farm_id, False)] == [first, second]
    slots = _rows(db, farm_id, True)
    # The 03:00 slot from the first fetch is before the second fetch, so it stays; the
    # 06:00 and 09:00 slots are replaced by the second fetch's 06:00 and 09:00.
    assert [(s.forecast_for.hour, s.temp_c, s.fetched_at) for s in slots] == [
        (3, Decimal("27"), first),
        (6, Decimal("30"), second),
        (9, Decimal("30"), second),
    ]
    assert _rows(db, two_farms[1], True) == []


def test_replacement_starts_at_an_earlier_new_slot(db, two_farms) -> None:
    farm_id = two_farms[0]
    first = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)
    weather_fetch_service.save_fetch(
        db, farm_id, _fetched(first, [first + timedelta(hours=3)], "27")
    )
    db.commit()

    # The second fetch at 03:30 still returns the 03:00 slot: it replaces, never duplicates.
    second = first + timedelta(hours=3, minutes=30)
    weather_fetch_service.save_fetch(
        db, farm_id, _fetched(second, [first + timedelta(hours=3)], "29")
    )
    db.commit()

    assert [(s.forecast_for.hour, s.temp_c) for s in _rows(db, farm_id, True)] == [
        (3, Decimal("29"))
    ]


def test_fetches_every_farm_and_skips_one_that_fails(
    db, two_farms, fake_key, caplog: pytest.LogCaptureFixture
) -> None:
    now = datetime.now(UTC)
    requests: list[httpx2.Request] = []
    client = _mock_client(now, failing_lat="12.500000", requests=requests)

    summary = weather_fetch_service.fetch_farms(client=client)

    first, second = two_farms
    assert summary.succeeded == [first]
    assert summary.failed == {second: "http_error"}
    assert len(_rows(db, first, False)) == 1
    assert len(_rows(db, first, True)) == 3
    assert _rows(db, second, False) == [] and _rows(db, second, True) == []
    assert all(r.url.params["appid"] == KEY for r in requests)
    assert f"farm {second}: http_error" in caplog.text
    assert KEY not in caplog.text


def test_fetches_only_the_given_farms(db, two_farms, fake_key) -> None:
    summary = weather_fetch_service.fetch_farms(
        [two_farms[1], 9999], client=_mock_client(datetime.now(UTC))
    )

    assert (summary.succeeded, summary.failed) == ([two_farms[1]], {})
    assert _rows(db, two_farms[0], False) == []


def test_missing_key_fails_every_farm_without_requests(
    two_farms, caplog: pytest.LogCaptureFixture
) -> None:
    requests: list[httpx2.Request] = []
    summary = weather_fetch_service.fetch_farms(
        client=_mock_client(datetime.now(UTC), requests=requests)
    )

    assert summary.succeeded == []
    assert summary.failed == {two_farms[0]: "missing_key", two_farms[1]: "missing_key"}
    assert requests == []
    assert "OPENWEATHERMAP_API_KEY is not set" in caplog.text


def test_an_unexpected_error_skips_only_that_farm(
    db, two_farms, fake_key, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    save = weather_fetch_service.save_fetch

    def save_or_fail(db, farm_id, fetched):
        if farm_id == two_farms[0]:
            raise RuntimeError(f"boom {KEY}")
        save(db, farm_id, fetched)

    monkeypatch.setattr(weather_fetch_service, "save_fetch", save_or_fail)

    summary = weather_fetch_service.fetch_farms(client=_mock_client(datetime.now(UTC)))

    assert summary.failed == {two_farms[0]: "unexpected_error"}
    assert summary.succeeded == [two_farms[1]]
    assert "RuntimeError" in caplog.text and KEY not in caplog.text


def test_new_farm_fetch_never_raises(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    def broken(farm_ids):
        raise RuntimeError("database down")

    monkeypatch.setattr(weather_fetch_service, "fetch_farms", broken)

    weather_fetch_service.fetch_new_farm(7)

    assert "new farm 7: RuntimeError" in caplog.text


def test_farm_setup_fetches_the_new_farm_in_the_background(
    client: TestClient,
    db,
    member_token: str,
    barangay_id: int,
    variety_ids,
    fake_key,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    monkeypatch.setattr(openweathermap_service, "make_client", lambda: _mock_client(now))

    response = client.post(
        "/api/v1/farms",
        json=_setup_body(barangay_id, variety_ids),
        headers=auth_header(member_token),
    )

    assert response.status_code == 201
    farm_id = response.json()["farm_id"]
    assert len(_rows(db, farm_id, False)) == 1 and len(_rows(db, farm_id, True)) == 3
    weather = client.get(f"/api/v1/farms/{farm_id}/weather", headers=auth_header(member_token))
    assert weather.json()["current"]["temp_c"] == 28.5


@pytest.mark.parametrize("failure", ["missing_key", "http_error"])
def test_a_failed_fetch_after_setup_keeps_the_201(
    client: TestClient,
    db,
    member_token: str,
    barangay_id: int,
    variety_ids,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    if failure == "http_error":
        monkeypatch.setattr(get_settings(), "openweathermap_api_key", SecretStr(KEY))
        monkeypatch.setattr(
            openweathermap_service,
            "make_client",
            lambda: httpx2.Client(
                transport=httpx2.MockTransport(lambda request: httpx2.Response(500))
            ),
        )

    response = client.post(
        "/api/v1/farms",
        json=_setup_body(barangay_id, variety_ids),
        headers=auth_header(member_token),
    )

    assert response.status_code == 201
    assert db.scalar(select(func.count()).select_from(WeatherLog)) == 0


def _patch_cli_client(monkeypatch: pytest.MonkeyPatch, **kwargs) -> None:
    now = datetime.now(UTC)
    monkeypatch.setattr(openweathermap_service, "make_client", lambda: _mock_client(now, **kwargs))


def test_cli_fetches_every_farm(two_farms, fake_key, monkeypatch, capsys, caplog) -> None:
    _patch_cli_client(monkeypatch)

    assert cli.main(["fetch-weather"]) == 0

    out = capsys.readouterr()
    assert "Weather fetched: 2 farms succeeded, 0 failed." in out.out
    assert KEY not in out.out + out.err + caplog.text


def test_cli_reports_failed_farms(two_farms, fake_key, monkeypatch, capsys, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    _patch_cli_client(monkeypatch, failing_lat="12.500000")

    assert cli.main(["fetch-weather"]) == 1

    out = capsys.readouterr()
    assert "Weather fetched: 1 farms succeeded, 1 failed." in out.out
    assert f"farm {two_farms[1]}: http_error" in caplog.text
    assert KEY not in out.out + out.err + caplog.text


def test_cli_fetches_one_farm(db, two_farms, fake_key, monkeypatch, capsys) -> None:
    _patch_cli_client(monkeypatch)

    assert cli.main(["fetch-weather", "--farm-id", str(two_farms[1])]) == 0

    assert "1 farms succeeded, 0 failed" in capsys.readouterr().out
    assert _rows(db, two_farms[0], False) == []


def test_cli_unknown_farm(two_farms, fake_key, capsys) -> None:
    assert cli.main(["fetch-weather", "--farm-id", "9999"]) == 1

    assert "Farm 9999 not found." in capsys.readouterr().err


def test_cli_without_a_key(two_farms, capsys) -> None:
    assert cli.main(["fetch-weather"]) == 1

    out = capsys.readouterr()
    assert "OPENWEATHERMAP_API_KEY is not set" in out.err
    assert "0 farms succeeded, 2 failed" in out.out
