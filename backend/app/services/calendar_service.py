"""Crop calendar (DFD 2.3, 2.5, 2.6; Section 6 "Crop calendar (Phase 7)").

Generation copies a variety's template tasks into dated activities when a cycle is created:
scheduled_date is the anchor date (planting_date or expected_harvest_date) plus day_offset,
end_date comes from day_offset_end the same way, and a repeating task becomes one task per
date up to its repeat_until point. Tasks on a harvested or failed cycle are read-only."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.seasons import philippine_today
from app.models import (
    CalendarTemplateTask,
    Crop,
    CropActivity,
    CropCycle,
    CropVariety,
    FarmAssignment,
    FarmField,
    Notification,
    User,
    WeatherAlert,
)
from app.models.enums import ActivityStatus, CalendarAnchor, CycleStatus, TaskType
from app.schemas.activity import (
    ActivityCreate,
    ActivityItem,
    ActivityUpdate,
    CycleActivities,
    CycleCalendar,
    FarmActivities,
    FarmActivityItem,
)
from app.services.farm_service import planting_window, require_farm_member

OPEN_CYCLE = (CycleStatus.PLANNED, CycleStatus.ACTIVE)
FINISHED = (ActivityStatus.DONE, ActivityStatus.SKIPPED)
_CLIENT_UUID_CONSTRAINT = "uq_crop_activity_client_uuid"


# ---------- Generation ----------


def _anchor_date(cycle: CropCycle, anchor: CalendarAnchor) -> date:
    return cycle.planting_date if anchor == CalendarAnchor.SOWING else cycle.expected_harvest_date


def template_dates(task: CalendarTemplateTask, cycle: CropCycle) -> list[tuple[date, date | None]]:
    """(scheduled_date, end_date) for each task one template row makes for this cycle."""
    anchor = _anchor_date(cycle, task.anchor)
    start = anchor + timedelta(days=task.day_offset)
    length = None
    if task.day_offset_end is not None:
        length = timedelta(days=task.day_offset_end - task.day_offset)
    if task.repeat_every_days is None:
        starts = [start]
    else:
        last = _anchor_date(cycle, task.repeat_until_anchor) + timedelta(
            days=task.repeat_until_offset
        )
        step = timedelta(days=task.repeat_every_days)
        starts = []
        day = start
        while day <= last:
            starts.append(day)
            day += step
    return [(day, day + length if length is not None else None) for day in starts]


def generate_for_cycle(db: Session, cycle: CropCycle) -> int:
    """Add the cycle's tasks from its variety's templates; the caller commits, so a new
    cycle and its calendar are saved together. Returns the number of tasks added."""
    templates = db.scalars(
        select(CalendarTemplateTask)
        .where(CalendarTemplateTask.variety_id == cycle.variety_id)
        .order_by(CalendarTemplateTask.template_task_id)
    ).all()
    activities = [
        CropActivity(
            cycle_id=cycle.cycle_id,
            template_task_id=task.template_task_id,
            title=task.task_name,
            scheduled_date=scheduled,
            end_date=end,
            reminder=False,
            task_type=task.task_type,
            growth_stage=task.growth_stage,
            is_weather_sensitive=task.is_weather_sensitive,
            client_uuid=uuid.uuid4(),
        )
        for task in templates
        for scheduled, end in template_dates(task, cycle)
    ]
    db.add_all(activities)
    return len(activities)


@dataclass
class GenerationSummary:
    """Tasks added per cycle, and the cycles skipped (closed, or already with tasks)."""

    generated: dict[int, int]
    skipped: list[int]


def generate_missing(db: Session, cycle_id: int | None = None) -> GenerationSummary | None:
    """Generate tasks for planned or active cycles that have none (cycles created before
    Phase 7). Never duplicates: a cycle with any task is skipped. None when cycle_id is
    given and doesn't exist."""
    query = select(CropCycle).order_by(CropCycle.cycle_id)
    if cycle_id is not None:
        query = query.where(CropCycle.cycle_id == cycle_id)
    cycles = db.scalars(query.with_for_update()).all()
    if cycle_id is not None and not cycles:
        return None
    summary = GenerationSummary(generated={}, skipped=[])
    for cycle in cycles:
        has_tasks = db.scalar(select(exists().where(CropActivity.cycle_id == cycle.cycle_id)))
        if cycle.status not in OPEN_CYCLE or has_tasks:
            summary.skipped.append(cycle.cycle_id)
            continue
        summary.generated[cycle.cycle_id] = generate_for_cycle(db, cycle)
    db.commit()
    return summary


# ---------- Reading ----------


def _item_columns():
    return (
        CropActivity,
        CalendarTemplateTask.description,
        CalendarTemplateTask.source_reference,
    )


def _ordered(query):
    return query.outerjoin(
        CalendarTemplateTask,
        CalendarTemplateTask.template_task_id == CropActivity.template_task_id,
    ).order_by(
        CropActivity.scheduled_date,
        CropActivity.scheduled_time.asc().nulls_last(),
        CropActivity.activity_id,
    )


def _item_fields(activity: CropActivity, description, source_reference) -> dict:
    return {
        "activity_id": activity.activity_id,
        "title": activity.title,
        "description": description,
        "source_reference": source_reference,
        "task_type": activity.task_type,
        "growth_stage": activity.growth_stage,
        "scheduled_date": activity.scheduled_date,
        "end_date": activity.end_date,
        "scheduled_time": activity.scheduled_time,
        "reminder": activity.reminder,
        "notes": activity.notes,
        "status": activity.status,
        "completed_at": activity.completed_at,
        "is_weather_sensitive": activity.is_weather_sensitive,
        "is_custom": activity.template_task_id is None,
    }


def _item(db: Session, activity: CropActivity) -> ActivityItem:
    template = (
        db.get(CalendarTemplateTask, activity.template_task_id)
        if activity.template_task_id is not None
        else None
    )
    return ActivityItem(
        **_item_fields(
            activity,
            template.description if template else None,
            template.source_reference if template else None,
        )
    )


def _filtered(query, status: ActivityStatus | None, from_: date | None, to: date | None):
    """A task matches from/to when any day of its range falls between them."""
    if status is not None:
        query = query.where(CropActivity.status == status)
    if from_ is not None:
        query = query.where(
            func.coalesce(CropActivity.end_date, CropActivity.scheduled_date) >= from_
        )
    if to is not None:
        query = query.where(CropActivity.scheduled_date <= to)
    return query


def completion_pct(done: int, total: int) -> int:
    if total == 0:
        return 0
    share = Decimal(done) * 100 / Decimal(total)
    return int(share.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _member_cycle(db: Session, user: User, cycle_id: int, lock: bool = False):
    """(cycle, field) for a cycle on one of the caller's farms; 404 cycle_not_found
    otherwise, so cycle IDs on other farms are never revealed."""
    query = (
        select(CropCycle, FarmField)
        .join(FarmField, FarmField.field_id == CropCycle.field_id)
        .join(FarmAssignment, FarmAssignment.farm_id == FarmField.farm_id)
        .where(CropCycle.cycle_id == cycle_id, FarmAssignment.user_id == user.user_id)
    )
    if lock:
        query = query.with_for_update(of=CropCycle)
    row = db.execute(query).first()
    if row is None:
        raise AppError(404, "cycle_not_found")
    return row


def list_cycle_activities(
    db: Session,
    user: User,
    cycle_id: int,
    status: ActivityStatus | None = None,
    from_: date | None = None,
    to: date | None = None,
) -> CycleActivities:
    """The cycle and its tasks; completion counts every task, whatever the filters.

    Errors: 404 cycle_not_found."""
    cycle, field = _member_cycle(db, user, cycle_id)
    variety_name, crop_name = db.execute(
        select(CropVariety.variety_name, Crop.crop_name)
        .join(Crop, Crop.crop_id == CropVariety.crop_id)
        .where(CropVariety.variety_id == cycle.variety_id)
    ).one()
    total, finished = db.execute(
        select(func.count(), func.count().filter(CropActivity.status.in_(FINISHED))).where(
            CropActivity.cycle_id == cycle_id
        )
    ).one()
    rows = db.execute(
        _filtered(
            _ordered(select(*_item_columns()).where(CropActivity.cycle_id == cycle_id)),
            status,
            from_,
            to,
        )
    )
    return CycleActivities(
        cycle=CycleCalendar(
            cycle_id=cycle.cycle_id,
            field_name=field.field_name,
            crop_name=crop_name,
            variety_name=variety_name,
            season=cycle.season,
            planting_date=cycle.planting_date,
            expected_harvest_date=cycle.expected_harvest_date,
            status=cycle.status,
            completion_pct=completion_pct(finished, total),
        ),
        items=[ActivityItem(**_item_fields(*row)) for row in rows],
    )


def current_cycle_ids(db: Session, farm_id: int) -> dict[int, int]:
    """field_id -> the field's current cycle: the planned or active one with the newest
    sowing date (then the newest cycle), as in GET /farms/{farm_id}/fields."""
    rows = db.execute(
        select(CropCycle.field_id, CropCycle.cycle_id)
        .join(FarmField, FarmField.field_id == CropCycle.field_id)
        .where(FarmField.farm_id == farm_id, CropCycle.status.in_(OPEN_CYCLE))
        .order_by(CropCycle.planting_date.desc(), CropCycle.cycle_id.desc())
    )
    current: dict[int, int] = {}
    for field_id, cycle_id in rows:
        current.setdefault(field_id, cycle_id)
    return current


def list_farm_activities(
    db: Session,
    user: User,
    farm_id: int,
    *,
    field_id: int | None = None,
    status: ActivityStatus | None = None,
    q: str | None = None,
    from_: date | None = None,
    to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> FarmActivities:
    """Tasks of each field's current cycle; q matches titles, ignoring case.

    Errors: 403 not_farm_member (also for a farm that doesn't exist); 422 field_not_in_farm.
    """
    require_farm_member(db, user, farm_id)
    if (
        field_id is not None
        and db.scalar(
            select(FarmField.field_id).where(
                FarmField.field_id == field_id, FarmField.farm_id == farm_id
            )
        )
        is None
    ):
        raise AppError(422, "field_not_in_farm")
    current = current_cycle_ids(db, farm_id)
    if field_id is not None:
        current = {field_id: current[field_id]} if field_id in current else {}
    if not current:
        return FarmActivities(items=[])

    query = (
        select(*_item_columns(), CropActivity.cycle_id, FarmField.field_name)
        .join(CropCycle, CropCycle.cycle_id == CropActivity.cycle_id)
        .join(FarmField, FarmField.field_id == CropCycle.field_id)
        .where(CropActivity.cycle_id.in_(list(current.values())))
    )
    if q and q.strip():
        pattern = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(CropActivity.title.ilike(f"%{pattern}%", escape="\\"))
    rows = db.execute(_filtered(_ordered(query), status, from_, to).limit(limit).offset(offset))
    return FarmActivities(
        items=[
            FarmActivityItem(
                **_item_fields(activity, description, source),
                cycle_id=cycle_id,
                field_name=field_name,
            )
            for activity, description, source, cycle_id, field_name in rows
        ]
    )


# ---------- Changing ----------


def _check_date(day: date) -> None:
    first, last = planting_window(philippine_today())
    if not first <= day <= last:
        raise AppError(422, "date_out_of_range")


def _require_open(cycle: CropCycle) -> None:
    if cycle.status not in OPEN_CYCLE:
        raise AppError(409, "cycle_closed")


def _existing_by_uuid(db: Session, client_uuid: uuid.UUID, cycle_id: int):
    """The task already saved with this client_uuid on this cycle; 409 client_uuid_taken
    when it was saved on another cycle; None when it is new."""
    existing = db.scalar(select(CropActivity).where(CropActivity.client_uuid == client_uuid))
    if existing is None:
        return None
    if existing.cycle_id != cycle_id:
        raise AppError(409, "client_uuid_taken")
    return existing


def create_activity(
    db: Session, user: User, cycle_id: int, data: ActivityCreate, now: datetime | None = None
) -> tuple[ActivityItem, bool]:
    """Add a custom task; (task, is_new). A client_uuid already saved on this cycle returns
    that task instead of a duplicate.

    Errors in order: 404 cycle_not_found; 409 client_uuid_taken; 409 cycle_closed;
    422 date_out_of_range."""
    cycle, _field = _member_cycle(db, user, cycle_id, lock=True)
    existing = _existing_by_uuid(db, data.client_uuid, cycle_id)
    if existing is not None:
        return _item(db, existing), False
    _require_open(cycle)
    _check_date(data.scheduled_date)

    activity = CropActivity(
        cycle_id=cycle_id,
        template_task_id=None,
        title=data.title,
        scheduled_date=data.scheduled_date,
        scheduled_time=data.scheduled_time,
        reminder=data.reminder,
        notes=data.notes,
        task_type=TaskType.OTHER,
        growth_stage=data.growth_stage,
        is_weather_sensitive=False,
        status=ActivityStatus.PENDING,
        client_uuid=data.client_uuid,
        updated_at=now or datetime.now(UTC),
    )
    db.add(activity)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint != _CLIENT_UUID_CONSTRAINT:
            raise
        # The same entry was saved by a request racing this one.
        existing = _existing_by_uuid(db, data.client_uuid, cycle_id)
        return _item(db, existing), False
    return _item(db, activity), True


def _member_activity(db: Session, user: User, activity_id: int):
    """(task, cycle) for a task on one of the caller's farms, locked; 404
    activity_not_found otherwise."""
    row = db.execute(
        select(CropActivity, CropCycle)
        .join(CropCycle, CropCycle.cycle_id == CropActivity.cycle_id)
        .join(FarmField, FarmField.field_id == CropCycle.field_id)
        .join(FarmAssignment, FarmAssignment.farm_id == FarmField.farm_id)
        .where(CropActivity.activity_id == activity_id, FarmAssignment.user_id == user.user_id)
        .with_for_update(of=CropActivity)
    ).first()
    if row is None:
        raise AppError(404, "activity_not_found")
    return row


def update_activity(
    db: Session, user: User, activity_id: int, data: ActivityUpdate, now: datetime | None = None
) -> ActivityItem:
    """Change a task. Done sets completed_at and leaving done clears it. A new date or time
    is a reschedule: the status becomes 'rescheduled' unless the task is done, end_date
    moves by the same number of days, and reminded_at is cleared. An unchanged value is not
    a change.

    Errors in order: 404 activity_not_found; 409 cycle_closed; 422 not_editable (title or
    growth_stage on a generated task), date_out_of_range."""
    now = now or datetime.now(UTC)
    activity, cycle = _member_activity(db, user, activity_id)
    _require_open(cycle)
    changes = {
        name: value
        for name, value in data.model_dump(exclude_unset=True).items()
        if getattr(activity, name) != value
    }
    if activity.template_task_id is not None and {"title", "growth_stage"} & changes.keys():
        raise AppError(422, "not_editable")
    if "scheduled_date" in changes:
        _check_date(changes["scheduled_date"])
    if not changes:
        return _item(db, activity)

    if "scheduled_date" in changes:
        moved = changes["scheduled_date"] - activity.scheduled_date
        if activity.end_date is not None:
            activity.end_date += moved
    if "status" in changes:
        status = ActivityStatus(changes.pop("status"))
        activity.status = status
        activity.completed_at = now if status == ActivityStatus.DONE else None
    for name, value in changes.items():
        setattr(activity, name, value)
    if {"scheduled_date", "scheduled_time"} & changes.keys():
        activity.reminded_at = None
        if activity.status != ActivityStatus.DONE:
            activity.status = ActivityStatus.RESCHEDULED
    activity.updated_at = now
    db.commit()
    return _item(db, activity)


def delete_activity(db: Session, user: User, activity_id: int) -> None:
    """Delete a custom task. Generated tasks can only be skipped, so the guides' schedule
    stays traceable. Its reminders go with it, and alerts that named it keep their text but
    no longer link to it.

    Errors in order: 404 activity_not_found; 409 cycle_closed, generated_task."""
    activity, cycle = _member_activity(db, user, activity_id)
    _require_open(cycle)
    if activity.template_task_id is not None:
        raise AppError(409, "generated_task")
    db.execute(
        update(WeatherAlert).where(WeatherAlert.activity_id == activity_id).values(activity_id=None)
    )
    for notification in db.scalars(
        select(Notification).where(Notification.activity_id == activity_id)
    ):
        db.delete(notification)
    db.delete(activity)
    db.commit()
