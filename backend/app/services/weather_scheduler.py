"""Weather scheduler (Section 5): fetches every farm at start and then every 3 hours, and
checks task reminders at start and then every 15 minutes (Phase 7).

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

from app.services import reminder_service, weather_fetch_service
from app.services.weather_fetch_service import FetchSummary

INTERVAL_HOURS = 3
JOB_ID = "fetch-weather"
REMINDER_MINUTES = 15
REMINDER_JOB_ID = "send-reminders"

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
    """A scheduler with two jobs, both run now: the weather fetch every INTERVAL_HOURS hours
    and the reminder check every REMINDER_MINUTES minutes."""
    start = now or datetime.now(UTC)
    scheduler = BlockingScheduler(timezone=UTC)
    for job, trigger, job_id in (
        (run_once, IntervalTrigger(hours=INTERVAL_HOURS, timezone=UTC), JOB_ID),
        (
            reminder_service.run_once,
            IntervalTrigger(minutes=REMINDER_MINUTES, timezone=UTC),
            REMINDER_JOB_ID,
        ),
    ):
        scheduler.add_job(
            job,
            trigger,
            id=job_id,
            next_run_time=start,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=None,
        )
    return scheduler


def run_forever(scheduler: BlockingScheduler | None = None) -> None:
    """Start the scheduler and block until Ctrl+C, then shut it down cleanly."""
    scheduler = scheduler or build_scheduler()
    logger.info(
        "Weather scheduler started: weather every %d hours, reminders every %d minutes, "
        "first runs now",
        INTERVAL_HOURS,
        REMINDER_MINUTES,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Weather scheduler stopping; a run in progress finishes first")
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=True)
    logger.info("Weather scheduler stopped")
