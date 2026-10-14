"""Weather scheduler (Section 5): fetches every farm at start and then every 3 hours.

It runs as its own process (`python -m app.cli weather-scheduler`), never inside the API
server, so uvicorn reloads and extra workers never start a second copy. Within the process,
max_instances=1 keeps runs from overlapping: a run still going when the next is due makes
that next run wait, and coalesce=True folds several missed runs into one."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services import weather_fetch_service
from app.services.weather_fetch_service import FetchSummary

INTERVAL_HOURS = 3
JOB_ID = "fetch-weather"

logger = logging.getLogger("app.weather")


def run_once(
    fetch: Callable[[], FetchSummary] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FetchSummary | None:
    """One scheduled run over every farm, logged as one line. Never raises, so a bad run
    never stops the scheduler."""
    fetch = fetch or weather_fetch_service.fetch_farms
    started = clock()
    try:
        summary = fetch()
    except Exception as exc:  # the next run must still happen
        logger.error("Weather run failed after %.1f s: %s", clock() - started, type(exc).__name__)
        return None
    logger.info(
        "Weather run: %d farms fetched, %d failed, %.1f s",
        len(summary.succeeded),
        len(summary.failed),
        clock() - started,
    )
    return summary


def build_scheduler(now: datetime | None = None) -> BlockingScheduler:
    """A scheduler with one job: run_once now, then every INTERVAL_HOURS hours."""
    scheduler = BlockingScheduler(timezone=UTC)
    scheduler.add_job(
        run_once,
        IntervalTrigger(hours=INTERVAL_HOURS, timezone=UTC),
        id=JOB_ID,
        next_run_time=now or datetime.now(UTC),
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )
    return scheduler


def run_forever(scheduler: BlockingScheduler | None = None) -> None:
    """Start the scheduler and block until Ctrl+C, then shut it down cleanly."""
    scheduler = scheduler or build_scheduler()
    logger.info("Weather scheduler started: every %d hours, first run now", INTERVAL_HOURS)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Weather scheduler stopping; a run in progress finishes first")
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=True)
    logger.info("Weather scheduler stopped")
