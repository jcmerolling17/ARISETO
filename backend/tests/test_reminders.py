"""Task reminders (Section 6, "Crop calendar (Phase 7)"): one task_reminder per active member
for each pending or rescheduled task with reminder on and dated today (Philippine time),
once its time, or 06:00 when it has none, has passed; sent once."""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app import cli
from app.core.seasons import PHILIPPINE_TIME
from app.models import CropActivity, FarmAssignment, Notification, User
from app.services import reminder_service
from tests.conftest import WORKER_MOBILE, create_active_member

TODAY = date(2026, 11, 12)


def _ph(hour: int, minute: int = 0, day: date = TODAY) -> datetime:
    return datetime.combine(day, time(hour, minute), PHILIPPINE_TIME)


def _task(db, calendar_farm, title: str = "Basal fertilizer", **values) -> CropActivity:
    cycle_id = calendar_farm.cycle_ids["Field B"]
    task = db.scalar(
        select(CropActivity).where(CropActivity.cycle_id == cycle_id, CropActivity.title == title)
    )
    fields = {"scheduled_date": TODAY, "end_date": None, "reminder": True}
    fields.update(values)
    for name, value in fields.items():
        setattr(task, name, value)
    db.commit()
    return task


def _sent(db) -> list[Notification]:
    return list(db.scalars(select(Notification).order_by(Notification.notification_id)))


def _send(db, now: datetime) -> reminder_service.ReminderSummary:
    summary = reminder_service.send_due(db, now)
    db.expire_all()
    return summary


@pytest.fixture
def worker_id(db, calendar_farm) -> int:
    worker = create_active_member(
        db,
        first_name="Pedro",
        last_name="Reyes",
        mobile_no=WORKER_MOBILE,
        email="worker@example.com",
        member_no="MPMPC-0043",
    )
    db.add(
        FarmAssignment(farm_id=calendar_farm.farm_id, user_id=worker.user_id, role_on_farm="worker")
    )
    db.commit()
    return worker.user_id


def test_an_untimed_task_is_reminded_at_six(db, calendar_farm) -> None:
    task = _task(db, calendar_farm)
    assert _send(db, _ph(5, 59)).tasks == 0
    summary = _send(db, _ph(6, 0))
    assert (summary.tasks, summary.notifications) == (1, 1)
    assert db.get(CropActivity, task.activity_id).reminded_at == _ph(6, 0)


def test_a_timed_task_is_reminded_at_its_time(db, calendar_farm) -> None:
    _task(db, calendar_farm, scheduled_time=time(14, 30))
    assert _send(db, _ph(14, 29)).tasks == 0
    assert _send(db, _ph(14, 30)).tasks == 1


def test_reminders_are_sent_once(db, calendar_farm) -> None:
    _task(db, calendar_farm)
    assert _send(db, _ph(6, 0)).tasks == 1
    assert _send(db, _ph(6, 15)).tasks == 0
    assert len(_sent(db)) == 1


def test_the_notification_text(db, calendar_farm) -> None:
    task = _task(db, calendar_farm, scheduled_time=time(6, 30))
    _send(db, _ph(7, 0))

    [notification] = _sent(db)
    assert notification.type == "task_reminder"
    assert notification.activity_id == task.activity_id
    assert notification.farm_id == calendar_farm.farm_id
    assert notification.alert_id is None
    assert notification.severity is None
    assert notification.title == "Task today: Basal fertilizer"
    assert notification.body == "Field B: Basal fertilizer, Nov 12, 6:30 AM"


def test_an_untimed_body_has_no_time(db, calendar_farm) -> None:
    _task(db, calendar_farm)
    _send(db, _ph(6, 0))
    assert _sent(db)[0].body == "Field B: Basal fertilizer, Nov 12"


def test_a_long_title_is_cut_to_fit(db, calendar_farm) -> None:
    _task(db, calendar_farm, title="Weed control")
    task = db.scalar(
        select(CropActivity).where(
            CropActivity.title == "Weed control", CropActivity.reminder.is_(True)
        )
    )
    task.title = "x" * 100
    db.commit()
    _send(db, _ph(6, 0))
    title = _sent(db)[0].title
    assert len(title) == 100 and title.endswith("…")


@pytest.mark.parametrize(
    ("values", "due"),
    [
        ({"reminder": False}, False),
        ({"status": "done"}, False),
        ({"status": "skipped"}, False),
        ({"status": "rescheduled"}, True),
        ({"scheduled_date": TODAY + timedelta(days=1)}, False),
        ({"scheduled_date": TODAY - timedelta(days=1)}, False),
    ],
)
def test_which_tasks_are_due(db, calendar_farm, values: dict, due: bool) -> None:
    _task(db, calendar_farm, **values)
    assert _send(db, _ph(12, 0)).tasks == (1 if due else 0)


def test_today_is_the_philippine_date(db, calendar_farm) -> None:
    _task(db, calendar_farm)
    # 23:30 UTC on Nov 11 is 07:30 on Nov 12 in the Philippines.
    assert _send(db, datetime(2026, 11, 11, 23, 30, tzinfo=UTC)).tasks == 1


def test_each_active_member_gets_one(db, calendar_farm, worker_id: int) -> None:
    _task(db, calendar_farm)
    _send(db, _ph(6, 0))
    owner_id = db.scalar(select(User.user_id).where(User.mobile_no == "+639171234567"))
    assert sorted(n.user_id for n in _sent(db)) == sorted([owner_id, worker_id])


def test_inactive_members_get_none(db, calendar_farm, worker_id: int) -> None:
    db.get(User, worker_id).account_status = "deactivated"
    db.commit()
    _task(db, calendar_farm)
    summary = _send(db, _ph(6, 0))
    assert summary.notifications == 1
    assert worker_id not in [n.user_id for n in _sent(db)]


def test_rescheduling_sends_the_reminder_again(db, calendar_farm) -> None:
    task = _task(db, calendar_farm)
    _send(db, _ph(6, 0))
    # PATCH clears reminded_at on a reschedule.
    task = db.get(CropActivity, task.activity_id)
    task.reminded_at = None
    task.scheduled_date = TODAY + timedelta(days=1)
    db.commit()
    assert _send(db, _ph(6, 0, TODAY + timedelta(days=1))).tasks == 1
    assert len(_sent(db)) == 2


def test_run_once_never_raises(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    def broken(*_args, **_kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(reminder_service, "send_due", broken)
    assert reminder_service.run_once() is None
    assert "Reminder check failed: RuntimeError" in caplog.text


def test_cli_send_reminders(db, calendar_farm, capsys) -> None:
    from app.core.seasons import philippine_today

    _task(db, calendar_farm, scheduled_date=philippine_today(), scheduled_time=time(0, 0))
    assert cli.main(["send-reminders"]) == 0
    assert "Reminders sent: 1 tasks, 1 notifications." in capsys.readouterr().out


# ---------- Closed cycles ----------


def _due_task(db, calendar_farm, cycle_status: str) -> CropActivity:
    """Basal fertilizer on Field B, due now (today, untimed, reminder on), on a cycle with
    the given status."""
    from app.core.seasons import philippine_today
    from app.models import CropCycle

    task = _task(db, calendar_farm, scheduled_date=philippine_today(), scheduled_time=None)
    db.get(CropCycle, calendar_farm.cycle_ids["Field B"]).status = cycle_status
    db.commit()
    return task


def _after_six_today() -> datetime:
    from app.core.seasons import philippine_today

    return _ph(12, 0, philippine_today())


@pytest.mark.parametrize("cycle_status", ["harvested", "failed"])
def test_closed_cycles_send_no_reminder(db, calendar_farm, cycle_status: str) -> None:
    task = _due_task(db, calendar_farm, cycle_status)
    summary = _send(db, _after_six_today())
    assert (summary.tasks, summary.notifications) == (0, 0)
    assert _sent(db) == []
    assert db.get(CropActivity, task.activity_id).reminded_at is None


def test_an_active_cycle_still_sends_one(db, calendar_farm) -> None:
    task = _due_task(db, calendar_farm, "active")
    assert _send(db, _after_six_today()).tasks == 1
    assert len(_sent(db)) == 1
    assert db.get(CropActivity, task.activity_id).reminded_at is not None


@pytest.mark.parametrize(("cycle_status", "sent"), [("harvested", 0), ("failed", 0), ("active", 1)])
def test_cli_skips_closed_cycles(db, calendar_farm, capsys, cycle_status: str, sent: int) -> None:
    from datetime import time as clock_time

    task = _due_task(db, calendar_farm, cycle_status)
    task.scheduled_time = clock_time(0, 0)  # due whatever the time of day the test runs
    db.commit()

    assert cli.main(["send-reminders"]) == 0
    assert f"Reminders sent: {sent} tasks, {sent} notifications." in capsys.readouterr().out
    db.expire_all()
    assert (db.get(CropActivity, task.activity_id).reminded_at is None) is (sent == 0)


@pytest.mark.parametrize(("cycle_status", "sent"), [("harvested", 0), ("failed", 0), ("active", 1)])
def test_scheduler_job_skips_closed_cycles(db, calendar_farm, cycle_status: str, sent: int) -> None:
    from datetime import time as clock_time

    from app.services import weather_scheduler

    task = _due_task(db, calendar_farm, cycle_status)
    task.scheduled_time = clock_time(0, 0)
    db.commit()

    job = weather_scheduler.build_scheduler().get_job(weather_scheduler.REMINDER_JOB_ID)
    summary = job.func()
    db.expire_all()  # the job saved in its own session

    assert (summary.tasks, summary.notifications) == (sent, sent)
    assert len(_sent(db)) == sent
    assert (db.get(CropActivity, task.activity_id).reminded_at is None) is (sent == 0)
