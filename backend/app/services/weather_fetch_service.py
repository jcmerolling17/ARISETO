"""Fetch OpenWeatherMap for farms and save the readings in WEATHER_LOG (Sections 4 and 5).

Used by `python -m app.cli fetch-weather`, the weather scheduler, and the one-off fetch
after farm setup. A farm that fails is logged by reason (never with the key) and skipped;
it never stops the other farms. After each farm is saved, its alert rules are evaluated
(alert_service); a failed evaluation is logged and never changes the fetch result."""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import httpx2
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Farm, WeatherLog
from app.services import alert_service
from app.services import openweathermap_service as owm
from app.services.openweathermap_service import FetchedWeather, WeatherFetchError

logger = logging.getLogger("app.weather")


@dataclass
class FetchSummary:
    """Farm IDs that were saved, and the reason each failed farm was skipped."""

    succeeded: list[int] = field(default_factory=list)
    failed: dict[int, str] = field(default_factory=dict)


def error_name(exc: Exception) -> str:
    """The error type, plus the database constraint when one failed (for example
    "IntegrityError (fk_weather_alert_weather_id_weather_log)"). Never the error text, which
    could include the request URL and so the key."""
    constraint = getattr(getattr(getattr(exc, "orig", None), "diag", None), "constraint_name", None)
    name = type(exc).__name__
    return f"{name} ({constraint})" if constraint else name


def save_fetch(db: Session, farm_id: int, fetched: FetchedWeather) -> None:
    """Add the current reading, kept as history, and replace the farm's forecast slots from
    the fetch time on. Replacement starts at the earliest new slot when that is earlier, so
    a slot is never stored twice. The caller commits, so it is one transaction. An alert whose
    slot is replaced keeps its message; its weather_id clears (ON DELETE SET NULL)."""
    replace_from = min(
        [fetched.current["fetched_at"], *(slot["forecast_for"] for slot in fetched.forecast)]
    )
    db.execute(
        delete(WeatherLog).where(
            WeatherLog.farm_id == farm_id,
            WeatherLog.is_forecast.is_(True),
            WeatherLog.forecast_for >= replace_from,
        )
    )
    db.add(WeatherLog(farm_id=farm_id, **fetched.current))
    db.add_all(WeatherLog(farm_id=farm_id, **slot) for slot in fetched.forecast)


def fetch_farms(
    farm_ids: Iterable[int] | None = None,
    *,
    client: httpx2.Client | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> FetchSummary:
    """Fetch and save the weather for the given farms (every farm when None), each farm in
    its own transaction. Unknown IDs are ignored."""
    with session_factory() as db:
        query = select(Farm.farm_id, Farm.latitude, Farm.longitude).order_by(Farm.farm_id)
        if farm_ids is not None:
            query = query.where(Farm.farm_id.in_(list(farm_ids)))
        farms = db.execute(query).all()

    summary = FetchSummary()
    try:
        api_key = owm.configured_api_key()
    except WeatherFetchError:
        logger.error("Weather not fetched: OPENWEATHERMAP_API_KEY is not set")
        summary.failed = {farm.farm_id: "missing_key" for farm in farms}
        return summary

    own_client = client is None
    client = client or owm.make_client()
    try:
        for farm in farms:
            try:
                fetched = owm.fetch_weather(
                    farm.latitude, farm.longitude, api_key=api_key, client=client
                )
                with session_factory() as db:
                    save_fetch(db, farm.farm_id, fetched)
                    db.commit()
            except WeatherFetchError as exc:
                summary.failed[farm.farm_id] = exc.reason
                logger.warning("Weather fetch failed for farm %s: %s", farm.farm_id, exc)
            except Exception as exc:  # one bad farm must not stop the rest
                # Only the type and constraint are logged: an error's text could include the URL.
                summary.failed[farm.farm_id] = "unexpected_error"
                logger.error("Weather fetch failed for farm %s: %s", farm.farm_id, error_name(exc))
            else:
                summary.succeeded.append(farm.farm_id)
                # Logs and swallows its own errors, so a fetch never fails because of alerts.
                alert_service.evaluate_after_fetch(farm.farm_id, session_factory)
    finally:
        if own_client:
            client.close()
    return summary


def fetch_new_farm(farm_id: int) -> None:
    """Background task after farm setup, so Home has a reading right away. Never raises:
    a failed fetch is logged and the scheduler tries again on its next run."""
    try:
        fetch_farms([farm_id])
    except Exception as exc:  # runs after the 201 response was sent
        logger.error("Weather fetch failed for new farm %s: %s", farm_id, error_name(exc))
