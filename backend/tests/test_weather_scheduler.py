"""Weather scheduler: job setup, the run function, start-up, and Ctrl+C. Nothing waits
3 hours and nothing reaches OpenWeatherMap."""

import logging
import threading
from datetime import UTC, datetime, timedelta

import pytest

from app import cli
from app.services import weather_scheduler
from app.services.weather_fetch_service import FetchSummary


def test_one_job_now_and_then_every_3_hours_without_overlap() -> None:
    start = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)
    scheduler = weather_scheduler.build_scheduler(now=start)

    (job,) = scheduler.get_jobs()
    assert job.id == "fetch-weather"
    assert job.func is weather_scheduler.run_once
    assert job.next_run_time == start  # the first run is at start
    assert job.trigger.interval == timedelta(hours=3)
    assert job.max_instances == 1  # runs never overlap
    assert job.coalesce is True  # missed runs fold into one
    assert job.misfire_grace_time is None  # a late run still happens
    assert job.trigger.get_next_fire_time(start, start) == start + timedelta(hours=3)
    assert not scheduler.running


def _clock(*ticks: float):
    values = iter(ticks)
    return lambda: next(values)


def test_a_run_logs_one_line(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.weather")
    summary = FetchSummary(succeeded=[1, 2], failed={3: "timeout"})

    result = weather_scheduler.run_once(fetch=lambda: summary, clock=_clock(10.0, 14.25))

    assert result is summary
    assert caplog.messages == ["Weather run: 2 farms fetched, 1 failed, 4.2 s"]


def test_a_failed_run_is_logged_and_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    def broken() -> FetchSummary:
        raise RuntimeError("database down")

    assert weather_scheduler.run_once(fetch=broken, clock=_clock(0.0, 1.5)) is None
    assert caplog.messages == ["Weather run failed after 1.5 s: RuntimeError"]


def test_the_default_run_fetches_every_farm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_fetch_farms(farm_ids=None):
        calls.append(farm_ids)
        return FetchSummary()

    monkeypatch.setattr(weather_scheduler.weather_fetch_service, "fetch_farms", fake_fetch_farms)

    weather_scheduler.run_once()

    assert calls == [None]


def test_starting_runs_the_job_right_away(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = threading.Event()
    scheduler = None

    def fake_run() -> None:
        ran.set()
        scheduler.shutdown(wait=False)

    monkeypatch.setattr(weather_scheduler, "run_once", fake_run)
    scheduler = weather_scheduler.build_scheduler()
    thread = threading.Thread(target=weather_scheduler.run_forever, args=(scheduler,))
    thread.start()
    thread.join(timeout=10)

    assert ran.is_set()
    assert not thread.is_alive()


class _StubScheduler:
    def __init__(self) -> None:
        self.running = False
        self.shutdown_calls: list[bool] = []

    def start(self) -> None:
        self.running = True
        raise KeyboardInterrupt

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)
        self.running = False


def test_ctrl_c_stops_cleanly(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.weather")
    scheduler = _StubScheduler()

    weather_scheduler.run_forever(scheduler)

    assert scheduler.shutdown_calls == [True]
    assert caplog.messages[-1] == "Weather scheduler stopped"


def test_cli_starts_the_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubScheduler()
    monkeypatch.setattr(weather_scheduler, "build_scheduler", lambda: stub)

    assert cli.main(["weather-scheduler"]) == 0
    assert stub.shutdown_calls == [True]
    assert logging.getLogger("apscheduler").level == logging.WARNING
