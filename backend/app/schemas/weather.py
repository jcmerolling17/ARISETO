from datetime import date, datetime

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


class DailyRange(BaseModel):
    """Lowest and highest temperature on one Philippine date."""

    date: date
    temp_min_c: float
    temp_max_c: float


class FarmWeather(BaseModel):
    """current is null and the lists are empty until the farm's weather has been fetched."""

    current: WeatherReading | None
    forecast: list[ForecastSlot]
    daily: list[DailyRange]
    alerts: list[dict]
