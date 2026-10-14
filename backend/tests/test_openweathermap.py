"""OpenWeatherMap client: requests, the WEATHER_LOG mapping (Section 4), and failures.
Every HTTP call goes to an httpx2 MockTransport; nothing reaches the network."""

import logging
from datetime import UTC, datetime
from decimal import Decimal

import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import Settings, get_settings
from app.services import openweathermap_service as owm
from app.services.openweathermap_service import (
    CURRENT_URL,
    FORECAST_URL,
    WeatherFetchError,
    fetch_weather,
)

KEY = "test-key-not-real"
LAT, LON = Decimal("13.271995"), Decimal("120.624727")
FETCHED_AT = datetime(2026, 10, 14, 3, 25, tzinfo=UTC)


def _dt(hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 10, 14, hour, minute, tzinfo=UTC).timestamp())


# Small made-up responses in OpenWeatherMap's shape, with only the fields the mapping reads.
CURRENT = {
    "dt": _dt(3, 20),
    "weather": [{"id": 500, "main": "Rain"}],
    "main": {"temp": 27.4, "feels_like": 30.9, "humidity": 84},
    "wind": {"speed": 3.6},
    "rain": {"1h": 0.42, "3h": 9.9},
}
FORECAST = {
    "list": [
        {
            "dt": _dt(3),
            "weather": [{"id": 500}],
            "main": {"temp": 27.1, "feels_like": 30.2, "humidity": 85},
            "wind": {"speed": 3.1},
            "rain": {"3h": 1.25, "1h": 9.9},
            "pop": 0.2,
        },
        {
            "dt": _dt(6),
            "weather": [{"id": 803}],
            "main": {"temp": 29.0, "feels_like": 32.5, "humidity": 78},
            "wind": {"speed": 4.2},
            "pop": 0.555,
        },
        {
            "dt": _dt(9),
            "weather": [{"id": 800}],
            "main": {"temp": 30.6, "feels_like": 34.0, "humidity": 70},
            "wind": {"speed": 5},
            "pop": 0,
        },
    ]
}


def _client(current=CURRENT, forecast=FORECAST, requests=None, status=200) -> httpx2.Client:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if requests is not None:
            requests.append(request)
        body = current if request.url.path.endswith("/weather") else forecast
        return httpx2.Response(status, json=body)

    return httpx2.Client(transport=httpx2.MockTransport(handler))


def _fetch(**kwargs):
    kwargs.setdefault("client", _client())
    return fetch_weather(LAT, LON, api_key=KEY, now=FETCHED_AT, **kwargs)


def test_calls_both_apis_in_metric_units_for_the_point() -> None:
    requests: list[httpx2.Request] = []
    _fetch(client=_client(requests=requests))

    assert [str(r.url.copy_with(query=None)) for r in requests] == [CURRENT_URL, FORECAST_URL]
    for request in requests:
        assert dict(request.url.params) == {
            "lat": "13.271995",
            "lon": "120.624727",
            "units": "metric",
            "appid": KEY,
        }


def test_maps_the_current_reading() -> None:
    current = _fetch().current

    assert current == {
        "forecast_for": datetime(2026, 10, 14, 3, 20, tzinfo=UTC),
        "temp_c": Decimal("27.4"),
        "feels_like_c": Decimal("30.9"),
        "humidity_pct": 84,
        "rain_mm": Decimal("0.42"),  # rain.1h, never rain.3h
        "wind_speed_mps": Decimal("3.6"),  # kept in m/s
        "condition_code": 500,
        "is_forecast": False,
        "fetched_at": FETCHED_AT,
        "precip_probability_pct": 20,  # from the 03:00 slot, the nearest to 03:20
    }
    assert current["forecast_for"].tzinfo is UTC


def test_maps_every_forecast_slot() -> None:
    forecast = _fetch().forecast

    assert [
        (s["forecast_for"].hour, s["rain_mm"], s["precip_probability_pct"], s["condition_code"])
        for s in forecast
    ] == [
        (3, Decimal("1.25"), 20, 500),  # rain.3h, never rain.1h
        (6, Decimal("0"), 56, 803),  # no rain object: 0; pop 0.555 -> 56
        (9, Decimal("0"), 0, 800),
    ]
    assert forecast[2] == {
        "forecast_for": datetime(2026, 10, 14, 9, tzinfo=UTC),
        "temp_c": Decimal("30.6"),
        "feels_like_c": Decimal("34.0"),
        "humidity_pct": 70,
        "rain_mm": Decimal("0"),
        "wind_speed_mps": Decimal("5"),
        "condition_code": 800,
        "is_forecast": True,
        "fetched_at": FETCHED_AT,
        "precip_probability_pct": 0,
    }


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [(3, 20, 20), (4, 40, 56), (4, 30, 20), (11, 0, 0), (0, 0, 20)],
)
def test_current_chance_of_rain_comes_from_the_nearest_slot(hour, minute, expected) -> None:
    # 04:30 is halfway between 03:00 and 06:00; the earlier slot wins the tie.
    current = {**CURRENT, "dt": _dt(hour, minute)}

    assert _fetch(client=_client(current=current)).current["precip_probability_pct"] == expected


def test_optional_values_may_be_missing() -> None:
    current = {"dt": _dt(3, 20), "weather": [{"id": 801}]}
    forecast = {"list": [{"dt": _dt(3), "weather": [{"id": 801}]}]}

    fetched = _fetch(client=_client(current=current, forecast=forecast))

    for row in (fetched.current, fetched.forecast[0]):
        assert row["temp_c"] is row["feels_like_c"] is row["humidity_pct"] is None
        assert row["wind_speed_mps"] is None and row["precip_probability_pct"] is None
        assert row["rain_mm"] == Decimal("0")


def test_empty_forecast_leaves_the_current_chance_of_rain_unknown() -> None:
    fetched = _fetch(client=_client(forecast={"list": []}))

    assert fetched.forecast == []
    assert fetched.current["precip_probability_pct"] is None


def test_missing_key_is_reported_before_any_request() -> None:
    requests: list[httpx2.Request] = []
    with pytest.raises(WeatherFetchError) as error:
        fetch_weather(LAT, LON, api_key="  ", client=_client(requests=requests))

    assert error.value.reason == "missing_key"
    assert requests == []


def test_key_defaults_to_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "openweathermap_api_key", None)
    with pytest.raises(WeatherFetchError, match="missing_key"):
        fetch_weather(LAT, LON, client=_client())

    requests: list[httpx2.Request] = []
    monkeypatch.setattr(get_settings(), "openweathermap_api_key", SecretStr(KEY))
    fetch_weather(LAT, LON, client=_client(requests=requests))
    assert requests[0].url.params["appid"] == KEY


@pytest.mark.parametrize(
    ("status", "reason"),
    [(401, "invalid_key"), (429, "rate_limited"), (500, "http_error"), (404, "http_error")],
)
def test_http_errors(status: int, reason: str) -> None:
    with pytest.raises(WeatherFetchError) as error:
        _fetch(client=_client(status=status))

    assert error.value.reason == reason


@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        (httpx2.ReadTimeout, "timeout"),
        (httpx2.ConnectTimeout, "timeout"),
        (httpx2.ConnectError, "network_error"),
    ],
)
def test_network_failures_never_reveal_the_key(exception, reason) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise exception(f"failed {request.url}", request=request)

    with pytest.raises(WeatherFetchError) as error:
        _fetch(client=httpx2.Client(transport=httpx2.MockTransport(handler)))

    assert error.value.reason == reason
    assert KEY not in str(error.value)
    # Raised `from None`, so the httpx2 error holding the URL is not chained or printed.
    assert error.value.__cause__ is None and error.value.__suppress_context__


def _bad(current=CURRENT, forecast=FORECAST) -> WeatherFetchError:
    with pytest.raises(WeatherFetchError) as error:
        _fetch(client=_client(current=current, forecast=forecast))
    assert KEY not in str(error.value)
    return error.value


@pytest.mark.parametrize(
    "current",
    [
        [],
        {**CURRENT, "dt": None},
        {**CURRENT, "dt": "today"},
        {**CURRENT, "weather": []},
        {**CURRENT, "weather": [{"main": "Rain"}]},
        {**CURRENT, "main": "hot"},
        {**CURRENT, "main": {"temp": "hot"}},
        {**CURRENT, "main": {"humidity": 140}},
        {**CURRENT, "rain": {"1h": "lots"}},
        {**CURRENT, "wind": {"speed": True}},
    ],
)
def test_bad_current_response(current) -> None:
    assert _bad(current=current).reason == "bad_response"


@pytest.mark.parametrize(
    "forecast",
    [
        {},
        {"list": "none"},
        {"list": ["slot"]},
        {"list": [{**FORECAST["list"][0], "pop": 1.5}]},
        {"list": [{**FORECAST["list"][0], "pop": "high"}]},
        {"list": [{**FORECAST["list"][0], "weather": None}]},
    ],
)
def test_bad_forecast_response(forecast) -> None:
    assert _bad(forecast=forecast).reason == "bad_response"


def test_non_json_response_is_a_bad_response() -> None:
    client = httpx2.Client(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200, text="<html>"))
    )
    with pytest.raises(WeatherFetchError) as error:
        _fetch(client=client)

    assert error.value.reason == "bad_response"


def test_default_client_has_a_timeout() -> None:
    with owm.make_client() as client:
        assert client.timeout.read == owm.TIMEOUT_SECONDS
        assert client.timeout.connect == owm.TIMEOUT_SECONDS


def test_settings_start_without_a_key_and_hide_it() -> None:
    required = {"database_url": "postgresql+psycopg://x@localhost/x", "secret_key": "s"}
    without = Settings(_env_file=None, **required)
    with_key = Settings(_env_file=None, openweathermap_api_key=KEY, **required)

    assert without.openweathermap_api_key is None
    assert with_key.openweathermap_api_key.get_secret_value() == KEY
    assert KEY not in repr(with_key) and KEY not in str(with_key.model_dump())


def test_debug_logging_never_shows_the_key(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    _fetch()
    with pytest.raises(WeatherFetchError):
        _fetch(client=_client(status=500))

    assert KEY not in caplog.text
    assert logging.getLogger("httpx2").getEffectiveLevel() == logging.WARNING
