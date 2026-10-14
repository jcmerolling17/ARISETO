"""Farm weather served from WEATHER_LOG; the provider is never called per request."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import FarmAssignment, User, WeatherLog
from app.schemas.weather import FarmWeather, ForecastSlot, WeatherReading


def farm_weather(db: Session, user: User, farm_id: int, now: datetime | None = None) -> FarmWeather:
    """The latest current reading and the upcoming forecast slots for a farm the caller
    owns or works on. An unknown farm is also 403 not_farm_member, since the caller can't
    be a member of it.

    A slot fetched more than once keeps only its newest fetch. Alerts stay empty until the
    WEATHER_ALERT table and the scheduler are built."""
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
            WeatherLog.forecast_for >= (now or datetime.now(UTC)),
        )
        .order_by(WeatherLog.forecast_for, WeatherLog.fetched_at.desc())
        .ext(distinct_on(WeatherLog.forecast_for))
    )
    return FarmWeather(
        current=WeatherReading.model_validate(current) if current else None,
        forecast=[ForecastSlot.model_validate(slot) for slot in slots],
        alerts=[],
    )
