"""Farm weather served from WEATHER_LOG; the provider is never called per request."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import FarmAssignment, User, WeatherLog
from app.schemas.weather import DailyRange, FarmWeather, ForecastSlot, WeatherReading

# Philippine time is UTC+8 all year (no daylight saving), so a fixed offset is exact.
PHILIPPINE_TIME = timezone(timedelta(hours=8), "PHT")


def daily_ranges(db: Session, farm_id: int, now: datetime) -> list[DailyRange]:
    """Lowest and highest temp_c for yesterday, today, and tomorrow in Philippine dates.
    Yesterday uses saved current readings only; today and tomorrow use current readings and
    forecast slots. Readings without a temperature are skipped, and a day with none is left
    out."""
    today = now.astimezone(PHILIPPINE_TIME).date()
    days = [today - timedelta(days=1), today, today + timedelta(days=1)]
    start = datetime.combine(days[0], time(), PHILIPPINE_TIME)
    end = datetime.combine(days[-1] + timedelta(days=1), time(), PHILIPPINE_TIME)
    rows = db.execute(
        select(WeatherLog.forecast_for, WeatherLog.temp_c, WeatherLog.is_forecast).where(
            WeatherLog.farm_id == farm_id,
            WeatherLog.temp_c.is_not(None),
            WeatherLog.forecast_for >= start,
            WeatherLog.forecast_for < end,
        )
    )
    temps: dict[date, list[Decimal]] = defaultdict(list)
    for forecast_for, temp_c, is_forecast in rows:
        day = forecast_for.astimezone(PHILIPPINE_TIME).date()
        if day == days[0] and is_forecast:
            continue
        temps[day].append(temp_c)
    return [
        DailyRange(date=day, temp_min_c=min(temps[day]), temp_max_c=max(temps[day]))
        for day in days
        if temps[day]
    ]


def farm_weather(db: Session, user: User, farm_id: int, now: datetime | None = None) -> FarmWeather:
    """The latest current reading, the upcoming forecast slots, and the daily ranges for a
    farm the caller owns or works on. An unknown farm is also 403 not_farm_member, since the
    caller can't be a member of it.

    Each fetch replaces the future slots, so every slot is stored once. Alerts stay empty
    until alert rules have a source."""
    now = now or datetime.now(UTC)
    is_member = db.scalar(
        select(FarmAssignment.assignment_id).where(
            FarmAssignment.farm_id == farm_id, FarmAssignment.user_id == user.user_id
        )
    )
    if is_member is None:
        raise AppError(403, "not_farm_member")

    current = db.scalar(
        select(WeatherLog)
        .where(WeatherLog.farm_id == farm_id, WeatherLog.is_forecast.is_(False))
        .order_by(WeatherLog.forecast_for.desc(), WeatherLog.fetched_at.desc())
        .limit(1)
    )
    slots = db.scalars(
        select(WeatherLog)
        .where(
            WeatherLog.farm_id == farm_id,
            WeatherLog.is_forecast.is_(True),
            WeatherLog.forecast_for >= now,
        )
        .order_by(WeatherLog.forecast_for)
    )
    return FarmWeather(
        current=WeatherReading.model_validate(current) if current else None,
        forecast=[ForecastSlot.model_validate(slot) for slot in slots],
        daily=daily_ranges(db, farm_id, now),
        alerts=[],
    )
