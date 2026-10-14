"""OpenWeatherMap client (Section 5): Current Weather and the 5 day / 3 hour Forecast in
metric units, turned into WEATHER_LOG row values (Section 4). Only the backend calls it.

The key travels in the request URL, and httpx2 puts that URL in its exception messages, so
every httpx2 error is replaced by a WeatherFetchError raised `from None`: the key never
reaches an error message, a traceback, or a log line."""

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx2

from app.core.config import get_settings

CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
TIMEOUT_SECONDS = 10.0

# httpx2 logs every request URL (key included) at INFO, so its loggers are kept at WARNING
# whatever level the app or the CLI logs at.
for _name in ("httpx2", "httpcore2"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class WeatherFetchError(Exception):
    """A fetch that produced no usable weather. `reason` is one of missing_key, invalid_key,
    rate_limited, http_error, timeout, network_error, or bad_response."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass
class FetchedWeather:
    """WEATHER_LOG values for one fetch, without farm_id: one current reading and the
    forecast slots, all stamped with the same fetched_at."""

    current: dict[str, Any]
    forecast: list[dict[str, Any]]


def make_client() -> httpx2.Client:
    return httpx2.Client(timeout=TIMEOUT_SECONDS)


def configured_api_key() -> str:
    """OPENWEATHERMAP_API_KEY from the settings; WeatherFetchError missing_key if unset."""
    return _api_key(None)


def _api_key(api_key: str | None) -> str:
    if api_key is None:
        secret = get_settings().openweathermap_api_key
        api_key = secret.get_secret_value() if secret else ""
    api_key = api_key.strip()
    if not api_key:
        raise WeatherFetchError("missing_key")
    return api_key


def _get_json(client: httpx2.Client, url: str, params: dict[str, str]) -> dict:
    try:
        response = client.get(url, params=params)
    except httpx2.TimeoutException:
        raise WeatherFetchError("timeout") from None
    except httpx2.HTTPError:
        raise WeatherFetchError("network_error") from None
    if response.status_code == 401:
        raise WeatherFetchError("invalid_key")
    if response.status_code == 429:
        raise WeatherFetchError("rate_limited")
    if response.status_code != 200:
        raise WeatherFetchError("http_error", f"HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        raise WeatherFetchError("bad_response", "not JSON") from None
    if not isinstance(data, dict):
        raise WeatherFetchError("bad_response", "not a JSON object")
    return data


def _section(item: dict, key: str) -> dict:
    """A nested object such as main, wind, or rain; {} when absent."""
    value = item.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise WeatherFetchError("bad_response", f"{key} is not an object")
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _number(value: Any, name: str) -> Decimal | None:
    if value is None:
        return None
    if not _is_number(value):
        raise WeatherFetchError("bad_response", f"{name} is not a number")
    return Decimal(str(value))


def _percent(value: Any, name: str) -> int | None:
    """A whole percentage from 0 to 100 (humidity_pct, precip_probability_pct)."""
    if value is None:
        return None
    if not _is_number(value) or not 0 <= value <= 100:
        raise WeatherFetchError("bad_response", f"{name} is outside 0 to 100")
    return round(value)


def _utc(value: Any) -> datetime:
    """OpenWeatherMap's dt (Unix seconds) as a UTC timestamp."""
    if not _is_number(value):
        raise WeatherFetchError("bad_response", "dt is missing")
    return datetime.fromtimestamp(value, UTC)


def _condition(item: dict) -> int:
    conditions = item.get("weather")
    if not isinstance(conditions, list) or not conditions or not isinstance(conditions[0], dict):
        raise WeatherFetchError("bad_response", "weather condition is missing")
    code = conditions[0].get("id")
    if not isinstance(code, int) or isinstance(code, bool):
        raise WeatherFetchError("bad_response", "weather condition is missing")
    return code


def _row(item: Any, rain_key: str, is_forecast: bool, fetched_at: datetime) -> dict[str, Any]:
    """Fields shared by current readings and forecast slots. rain_mm is rain.1h for the
    current reading and rain.3h for a forecast slot, 0 when absent."""
    if not isinstance(item, dict):
        raise WeatherFetchError("bad_response", "reading is not an object")
    main, wind, rain = _section(item, "main"), _section(item, "wind"), _section(item, "rain")
    rain_mm = _number(rain.get(rain_key), f"rain.{rain_key}")
    return {
        "forecast_for": _utc(item.get("dt")),
        "temp_c": _number(main.get("temp"), "main.temp"),
        "feels_like_c": _number(main.get("feels_like"), "main.feels_like"),
        "humidity_pct": _percent(main.get("humidity"), "main.humidity"),
        "rain_mm": Decimal("0") if rain_mm is None else rain_mm,
        "wind_speed_mps": _number(wind.get("speed"), "wind.speed"),
        "condition_code": _condition(item),
        "is_forecast": is_forecast,
        "fetched_at": fetched_at,
    }


def _forecast_slot(item: Any, fetched_at: datetime) -> dict[str, Any]:
    slot = _row(item, "3h", True, fetched_at)
    pop = item.get("pop")
    if pop is not None and (not _is_number(pop) or not 0 <= pop <= 1):
        raise WeatherFetchError("bad_response", "pop is outside 0 to 1")
    slot["precip_probability_pct"] = None if pop is None else round(pop * 100)
    return slot


def _nearest_slot_probability(current: dict, forecast: list[dict]) -> int | None:
    """Current Weather has no pop, so the current reading takes the chance of rain from the
    forecast slot nearest its time (the earlier slot on a tie)."""
    if not forecast:
        return None
    nearest = min(forecast, key=lambda slot: abs(slot["forecast_for"] - current["forecast_for"]))
    return nearest["precip_probability_pct"]


def fetch_weather(
    latitude: Decimal | float,
    longitude: Decimal | float,
    *,
    api_key: str | None = None,
    client: httpx2.Client | None = None,
    now: datetime | None = None,
) -> FetchedWeather:
    """Fetch the current weather and forecast for a point. api_key defaults to
    OPENWEATHERMAP_API_KEY; raises WeatherFetchError when the fetch fails."""
    params = {
        "lat": str(latitude),
        "lon": str(longitude),
        "units": "metric",
        "appid": _api_key(api_key),
    }
    fetched_at = now or datetime.now(UTC)
    own_client = client is None
    client = client or make_client()
    try:
        current_data = _get_json(client, CURRENT_URL, params)
        forecast_data = _get_json(client, FORECAST_URL, params)
    finally:
        if own_client:
            client.close()

    slots = forecast_data.get("list")
    if not isinstance(slots, list):
        raise WeatherFetchError("bad_response", "forecast list is missing")
    forecast = [_forecast_slot(item, fetched_at) for item in slots]
    current = _row(current_data, "1h", False, fetched_at)
    current["precip_probability_pct"] = _nearest_slot_probability(current, forecast)
    return FetchedWeather(current=current, forecast=forecast)
