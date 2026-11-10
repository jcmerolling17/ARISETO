"""Task reminders (Section 6, "Crop calendar (Phase 7)"): every 15 minutes the weather
scheduler sends one task_reminder notification to each active member of the farm for each
pending or rescheduled task with reminder on and dated today (Philippine time), once the
task's time, or 06:00 when it has none, has passed. reminded_at makes it once only. Tasks on
a harvested or failed cycle are skipped, since those cycles are read-only."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.seasons import PHILIPPINE_TIME
from app.db.session import SessionLocal
from app.models import CropActivity, CropCycle, FarmAssignment, FarmField, Notification, User
from app.models.enums import AccountStatus, ActivityStatus, CycleStatus, NotificationType

logger = logging.getLogger("app.calendar")

DEFAULT_TIME = time(6, 0)
TITLE_LIMIT = 100  # NOTIFICATION.title varchar(100)


def short_date(day: date) -> str:
    """'Nov 12'."""
    return f"{day:%b} {day.day}"


def clock(moment: time) -> str:
    """'6:30 AM'."""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def reminder_text(title: str, field_name: str, day: date, at: time | None) -> tuple[str, str]:
    """(title, body): "Task today: {title}" and "{field}: {title}, {Mon D}[, {h:mm AM}]"."""
    heading = f"Task today: {title}"
    if len(heading) > TITLE_LIMIT:
        heading = heading[: TITLE_LIMIT - 1] + "…"
    body = f"{field_name}: {title}, {short_date(day)}"
    if at is not None:
        body += f", {clock(at)}"
    return heading, body


@dataclass
class ReminderSummary:
    tasks: int = 0
    notifications: int = 0


def send_due(db: Session, now: datetime | None = None) -> ReminderSummary:
    """Send the reminders that are due and commit. Rows are locked and skipped when another
    run holds them, so two runs never send the same reminder."""
    now = now or datetime.now(UTC)
    local = now.astimezone(PHILIPPINE_TIME)
    rows = db.execute(
        select(CropActivity, FarmField)
        .join(CropCycle, CropCycle.cycle_id == CropActivity.cycle_id)
        .join(FarmField, FarmField.field_id == CropCycle.field_id)
        .where(
            # Tasks on a harvested or failed cycle are read-only, so they never remind.
            CropCycle.status.in_([CycleStatus.PLANNED, CycleStatus.ACTIVE]),
            CropActivity.reminder.is_(True),
            CropActivity.reminded_at.is_(None),
            CropActivity.status.in_([ActivityStatus.PENDING, ActivityStatus.RESCHEDULED]),
            CropActivity.scheduled_date == local.date(),
            func.coalesce(CropActivity.scheduled_time, DEFAULT_TIME) <= local.time(),
        )
        .order_by(CropActivity.activity_id)
        .with_for_update(of=CropActivity, skip_locked=True)
    ).all()

    summary = ReminderSummary()
    for activity, field in rows:
        members = db.scalars(
            select(FarmAssignment.user_id)
            .join(User, User.user_id == FarmAssignment.user_id)
            .where(
                FarmAssignment.farm_id == field.farm_id,
                User.account_status == AccountStatus.ACTIVE,
            )
            .order_by(FarmAssignment.user_id)
        ).all()
        heading, body = reminder_text(
            activity.title, field.field_name, activity.scheduled_date, activity.scheduled_time
        )
        db.add_all(
            Notification(
                user_id=user_id,
                farm_id=field.farm_id,
                activity_id=activity.activity_id,
                type=NotificationType.TASK_REMINDER,
                title=heading,
                body=body,
                severity=None,
                created_at=now,
            )
            for user_id in members
        )
        activity.reminded_at = now
        summary.tasks += 1
        summary.notifications += len(members)
    db.commit()
    return summary


def run_once(session_factory: Callable[[], Session] = SessionLocal) -> ReminderSummary | None:
    """One scheduled reminder check, logged when it sends anything. Never raises, so a bad
    run never stops the scheduler."""
    try:
        with session_factory() as db:
            summary = send_due(db)
    except Exception as exc:  # the next check must still happen
        logger.error("Reminder check failed: %s", type(exc).__name__)
        return None
    if summary.tasks:
        logger.info(
            "Reminders sent: %d tasks, %d notifications", summary.tasks, summary.notifications
        )
    return summary
