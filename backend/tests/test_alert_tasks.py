"""Weather alerts naming the weather-sensitive tasks in their window (Section 6, "Crop
calendar (Phase 7)"): pending or rescheduled tasks on planned or active cycles with any day
of their range between today and the window's last day, up to three named, then
"and N more"; activity_id is the earliest."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.seasons import PHILIPPINE_TIME
from app.models import AlertRule, CropActivity, CropCycle, Notification, WeatherLog
from app.services import alert_service

HOUR = timedelta(hours=1)
RAIN = (
    "Rain alert (PAGASA yellow level, 50 to 100 mm): about 60 mm of rain is forecast in the "
    "next 24 hours."
)


def _rain(db, farm_id: int, now: datetime) -> None:
    db.add(
        WeatherLog(
            farm_id=farm_id,
            forecast_for=now + 3 * HOUR,
            fetched_at=now,
            is_forecast=True,
            rain_mm=Decimal("60"),
            condition_code=500,
        )
    )
    db.commit()


def _task(db, cycle_id: int, title: str) -> CropActivity:
    return db.scalar(
        select(CropActivity).where(CropActivity.cycle_id == cycle_id, CropActivity.title == title)
    )


def _evaluate(db, farm_id: int, now: datetime):
    [alert] = alert_service.evaluate_farm(db, farm_id, now)
    db.commit()
    return alert


def _day(task: CropActivity) -> str:
    return f"{task.scheduled_date:%b} {task.scheduled_date.day}"


def test_names_the_tasks_in_the_window(db, calendar_farm) -> None:
    now = datetime.now(UTC)
    corn = calendar_farm.cycle_ids["Field A"]
    # Sown 30 days ago: hilling-up (days 21 to 30) and the first release (28 to 30) are
    # still running today; the second release (35 to 37) and rice's basal fertilizer
    # (7 to 10) are not.
    hilling = _task(db, corn, "Hilling-up with the second nitrogen side-dressing")
    first = _task(db, corn, "Trichogramma release for corn borer, first")
    _rain(db, calendar_farm.farm_id, now)

    alert = _evaluate(db, calendar_farm.farm_id, now)

    assert alert.message == (
        f"{RAIN} Tasks in this window: {hilling.title} (Field A, {_day(hilling)}), "
        f"{first.title} (Field A, {_day(first)})."
    )
    assert alert.activity_id == hilling.activity_id
    [notification] = db.scalars(select(Notification)).all()
    assert notification.body == alert.message


def test_names_three_then_and_n_more(db, calendar_farm) -> None:
    now = datetime.now(UTC)
    today = now.astimezone(PHILIPPINE_TIME).date()
    corn, rice = calendar_farm.cycle_ids["Field A"], calendar_farm.cycle_ids["Field B"]
    for cycle_id, title in (
        (corn, "Trichogramma release, second"),
        (corn, "Harvest"),
        (rice, "Basal fertilizer"),
        (rice, "Harvest at grain maturity"),
    ):
        task = _task(db, cycle_id, title)
        task.scheduled_date, task.end_date = today, None
    db.commit()
    _rain(db, calendar_farm.farm_id, now)

    alert = _evaluate(db, calendar_farm.farm_id, now)

    assert alert.message.endswith(" and 3 more.")
    assert alert.message.count(" (Field ") == 3
    hilling = _task(db, corn, "Hilling-up with the second nitrogen side-dressing")
    assert alert.activity_id == hilling.activity_id  # the earliest start date


def test_done_skipped_and_unsensitive_tasks_are_left_out(db, calendar_farm) -> None:
    now = datetime.now(UTC)
    corn = calendar_farm.cycle_ids["Field A"]
    _task(db, corn, "Hilling-up with the second nitrogen side-dressing").status = "done"
    _task(db, corn, "Trichogramma release for corn borer, first").status = "skipped"
    # Weed control runs days 0 to 30 too, but is not weather-sensitive.
    db.commit()
    _rain(db, calendar_farm.farm_id, now)

    alert = _evaluate(db, calendar_farm.farm_id, now)
    assert alert.message == RAIN
    assert alert.activity_id is None


def test_rescheduled_tasks_count(db, calendar_farm) -> None:
    now = datetime.now(UTC)
    corn = calendar_farm.cycle_ids["Field A"]
    _task(db, corn, "Hilling-up with the second nitrogen side-dressing").status = "rescheduled"
    db.commit()
    _rain(db, calendar_farm.farm_id, now)
    assert "Hilling-up" in _evaluate(db, calendar_farm.farm_id, now).message


def test_tasks_on_closed_cycles_are_left_out(db, calendar_farm) -> None:
    now = datetime.now(UTC)
    db.get(CropCycle, calendar_farm.cycle_ids["Field A"]).status = "harvested"
    db.commit()
    _rain(db, calendar_farm.farm_id, now)
    assert _evaluate(db, calendar_farm.farm_id, now).message == RAIN


def test_the_window_ends_on_its_last_philippine_day(db, calendar_farm) -> None:
    corn = calendar_farm.cycle_ids["Field A"]
    second = _task(db, corn, "Trichogramma release, second")
    for title in (
        "Hilling-up with the second nitrogen side-dressing",
        "Trichogramma release for corn borer, first",
    ):
        _task(db, corn, title).status = "done"
    db.commit()
    # 23:00 Philippine time the day before the second release starts: the 24-hour window
    # ends at 23:00 the next day, so the start date is its last day.
    start = second.scheduled_date
    now = datetime(start.year, start.month, start.day, 15, 0, tzinfo=UTC) - 24 * HOUR
    _rain(db, calendar_farm.farm_id, now)
    assert "Trichogramma release, second" in _evaluate(db, calendar_farm.farm_id, now).message


def test_affected_task_type_limits_the_tasks(db, calendar_farm) -> None:
    now = datetime.now(UTC)
    rule = db.scalar(select(AlertRule).where(AlertRule.rule_name.like("%yellow%")))
    rule.affected_task_type = "pest_control"
    db.commit()
    _rain(db, calendar_farm.farm_id, now)

    alert = _evaluate(db, calendar_farm.farm_id, now)
    assert "Trichogramma release for corn borer, first" in alert.message
    assert "Hilling-up" not in alert.message
