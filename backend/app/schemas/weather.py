from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WeatherReading(BaseModel):
    """One WEATHER_LOG row as GET /farms/{farm_id}/weather returns it. Numbers are JSON
    numbers; wind stays in m/s (the app converts it to km/h)."""

    model_config = ConfigDict(from_attributes=True)

    temp_c: float | None
    feels_like_c: float | None
    humidity_pct: int | None
    wind_speed_mps: float | None
    precip_probability_pct: int | None
    rain_mm: float | None
    condition_code: int
    fetched_at: datetime


class ForecastSlot(WeatherReading):
    forecast_for: datetime


class FarmWeather(BaseModel):
    """current is null and both lists are empty until the scheduler has fetched weather."""

    current: WeatherReading | None
    forecast: list[ForecastSlot]
    alerts: list[dict]
