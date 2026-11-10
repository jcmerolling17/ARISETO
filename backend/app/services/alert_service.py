"""Weather alert rules (DFD 5.2 and 5.3; Section 6, "Weather alert rules (Phase 8)").

After each fetch, every active rule is checked against the farm's latest fetched forecast:
the slots after the evaluation time and no later than lookahead_hours after it. A 'sum'
rule adds the slots' values and a 'max' rule takes the highest. For each parameter only the
highest firing threshold is issued, and only when it is higher than every alert already
issued for that farm and parameter in the past 24 hours. Each alert becomes one
notification for every farm member whose account is active.

Since Phase 7 an alert also names the weather-sensitive tasks in its window: pending or
rescheduled tasks on the farm's planned or active cycles with any day from scheduled_date to
end_date between today and the window's last day (Philippine dates), only of the rule's
affected_task_type when it is set. Up to three are named, then "and N more"; activity_id
points to the earliest."""

import logging
import math
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.seasons import PHILIPPINE_TIME
from app.db.session import SessionLocal
from app.models import (
    AlertRule,
    CropActivity,
    CropCycle,
    Farm,
    FarmAssignment,
    FarmField,
    Notification,
    User,
    WeatherAlert,
    WeatherLog,
)
from app.models.enums import (
    AccountStatus,
    ActivityStatus,
    AlertAggregation,
    AlertOperator,
    AlertParameter,
    CycleStatus,
    NotificationType,
)

logger = logging.getLogger("app.weather")

NO_REPEAT_HOURS = 24
KMH_PER_MPS = Decimal("3.6")

_COMPARE: dict[AlertOperator, Callable[[Decimal, Decimal], bool]] = {
    AlertOperator.GT: lambda value, threshold: value > threshold,
    AlertOperator.GE: lambda value, threshold: value >= threshold,
    AlertOperator.LT: lambda value, threshold: value < threshold,
    AlertOperator.LE: lambda value, threshold: value <= threshold,
}


def heat_index_c(temp_c: float, humidity_pct: float) -> float:
    """US National Weather Service heat index, in °C. Computed in °F: the simple formula
    first; at 80 °F or more, the Rothfusz regression with its low- and high-humidity
    adjustments instead."""
    t = temp_c * 9 / 5 + 32
    rh = humidity_pct
    hi = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if hi >= 80:
        hi = (
            -42.379
            + 2.04901523 * t
            + 10.14333127 * rh
            - 0.22475541 * t * rh
            - 0.00683783 * t * t
            - 0.05481717 * rh * rh
            + 0.00122874 * t * t * rh
            + 0.00085282 * t * rh * rh
            - 0.00000199 * t * t * rh * rh
        )
        if rh < 13 and 80 <= t <= 112:
            hi -= ((13 - rh) / 4) * math.sqrt((17 - abs(t - 95)) / 17)
        elif rh > 85 and 80 <= t <= 87:
            hi += ((rh - 85) / 10) * ((87 - t) / 5)
    return (hi - 32) * 5 / 9


def slot_value(slot: WeatherLog, parameter: AlertParameter) -> Decimal | None:
    """The slot's reading for a rule parameter; None when the reading is missing."""
    if parameter == AlertParameter.HEAT_INDEX_C:
        if slot.temp_c is None or slot.humidity_pct is None:
            return None
        return Decimal(repr(heat_index_c(float(slot.temp_c), float(slot.humidity_pct))))
    value = getattr(slot, parameter.value)
    return None if value is None else Decimal(value)


def window_slots(slots: Iterable[WeatherLog], now: datetime, hours: int) -> list[WeatherLog]:
    """Slots after now and no later than now + hours (start excluded, end included)."""
    end = now + timedelta(hours=hours)
    return [slot for slot in slots if now < slot.forecast_for <= end]


@dataclass
class RuleResult:
    """A rule's combined value over its window and the slot with the highest value."""

    value: Decimal
    slot: WeatherLog


def evaluate_rule(rule: AlertRule, slots: list[WeatherLog], now: datetime) -> RuleResult | None:
    """The rule's value when it fires, otherwise None. Slots without a reading are skipped;
    a window with no readings never fires. A tie for the highest slot goes to the earlier."""
    readings = [
        (value, slot)
        for slot in sorted(window_slots(slots, now, rule.lookahead_hours), key=_slot_time)
        if (value := slot_value(slot, rule.parameter)) is not None
    ]
    if not readings:
        return None
    # max keeps the first of equal values, and readings are in time order.
    top_value, top_slot = max(readings, key=lambda reading: reading[0])
    if rule.aggregation == AlertAggregation.SUM:
        value = sum((value for value, _ in readings), Decimal(0))
    else:
        value = top_value
    if not _COMPARE[rule.operator](value, rule.threshold):
        return None
    return RuleResult(value=value, slot=top_slot)


def _slot_time(slot: WeatherLog) -> datetime:
    return slot.forecast_for


def shown_value(parameter: AlertParameter, value: Decimal) -> int:
    """The value as the message shows it: whole mm or °C, and wind in whole km/h,
    rounded half up."""
    if parameter == AlertParameter.WIND_SPEED_MPS:
        value = value * KMH_PER_MPS
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def render_message(rule: AlertRule, value: Decimal) -> str:
    return rule.message_template.replace(
        "{value}", str(shown_value(rule.parameter, value))
    ).replace("{hours}", str(rule.lookahead_hours))


def latest_forecast(db: Session, farm_id: int) -> list[WeatherLog]:
    """The forecast slots saved by the farm's most recent fetch."""
    latest = (
        select(func.max(WeatherLog.fetched_at))
        .where(WeatherLog.farm_id == farm_id, WeatherLog.is_forecast.is_(True))
        .scalar_subquery()
    )
    return list(
        db.scalars(
            select(WeatherLog)
            .where(
                WeatherLog.farm_id == farm_id,
                WeatherLog.is_forecast.is_(True),
                WeatherLog.fetched_at == latest,
            )
            .order_by(WeatherLog.forecast_for)
        )
    )


def _recent_top_thresholds(
    db: Session, farm_id: int, now: datetime
) -> dict[AlertParameter, Decimal]:
    """The highest threshold already issued for each parameter on this farm in the past
    24 hours."""
    rows = db.execute(
        select(AlertRule.parameter, func.max(AlertRule.threshold))
        .join(WeatherAlert, WeatherAlert.rule_id == AlertRule.rule_id)
        .where(
            WeatherAlert.farm_id == farm_id,
            WeatherAlert.issued_at > now - timedelta(hours=NO_REPEAT_HOURS),
        )
        .group_by(AlertRule.parameter)
    )
    return {parameter: threshold for parameter, threshold in rows}


def _active_member_ids(db: Session, farm_id: int) -> list[int]:
    return list(
        db.scalars(
            select(FarmAssignment.user_id)
            .join(User, User.user_id == FarmAssignment.user_id)
            .where(
                FarmAssignment.farm_id == farm_id,
                User.account_status == AccountStatus.ACTIVE,
            )
            .order_by(FarmAssignment.user_id)
        )
    )


NAMED_TASKS = 3


def _short_date(day: date) -> str:
    return f"{day:%b} {day.day}"


def tasks_in_window(db: Session, farm_id: int, rule: AlertRule, now: datetime) -> list[tuple]:
    """(activity_id, title, field_name, scheduled_date) of the weather-sensitive tasks in
    the rule's window, earliest first."""
    first_day = now.astimezone(PHILIPPINE_TIME).date()
    last_day = (now + timedelta(hours=rule.lookahead_hours)).astimezone(PHILIPPINE_TIME).date()
    query = (
        select(
            CropActivity.activity_id,
            CropActivity.title,
            FarmField.field_name,
            CropActivity.scheduled_date,
        )
        .join(CropCycle, CropCycle.cycle_id == CropActivity.cycle_id)
        .join(FarmField, FarmField.field_id == CropCycle.field_id)
        .where(
            FarmField.farm_id == farm_id,
            CropCycle.status.in_([CycleStatus.PLANNED, CycleStatus.ACTIVE]),
            CropActivity.is_weather_sensitive.is_(True),
            CropActivity.status.in_([ActivityStatus.PENDING, ActivityStatus.RESCHEDULED]),
            CropActivity.scheduled_date <= last_day,
            func.coalesce(CropActivity.end_date, CropActivity.scheduled_date) >= first_day,
        )
        .order_by(
            CropActivity.scheduled_date,
            CropActivity.scheduled_time.asc().nulls_last(),
            CropActivity.activity_id,
        )
    )
    if rule.affected_task_type is not None:
        query = query.where(CropActivity.task_type == rule.affected_task_type)
    return [tuple(row) for row in db.execute(query)]


def tasks_sentence(tasks: list[tuple]) -> str:
    """'Tasks in this window: A (Field A, Nov 5), B (…), C (…) and 2 more.'"""
    named = ", ".join(
        f"{title} ({field_name}, {_short_date(day)})"
        for _, title, field_name, day in tasks[:NAMED_TASKS]
    )
    more = len(tasks) - NAMED_TASKS
    return f"Tasks in this window: {named}{f' and {more} more' if more > 0 else ''}."


def evaluate_farm(db: Session, farm_id: int, now: datetime | None = None) -> list[WeatherAlert]:
    """Issue the farm's alerts for its latest forecast and notify its active members; the
    caller commits. The farm row is locked, so two evaluations of one farm (the scheduler
    and fetch-weather) run one after the other."""
    now = now or datetime.now(UTC)
    if db.scalar(select(Farm.farm_id).where(Farm.farm_id == farm_id).with_for_update()) is None:
        return []
    slots = latest_forecast(db, farm_id)
    if not slots:
        return []

    by_parameter: dict[AlertParameter, list[AlertRule]] = defaultdict(list)
    for rule in db.scalars(
        select(AlertRule).where(AlertRule.is_active.is_(True)).order_by(AlertRule.rule_id)
    ):
        by_parameter[rule.parameter].append(rule)

    issued_before = _recent_top_thresholds(db, farm_id, now)
    issued: list[tuple[AlertRule, WeatherAlert]] = []
    for parameter, rules in by_parameter.items():
        firing = [(rule, result) for rule in rules if (result := evaluate_rule(rule, slots, now))]
        if not firing:
            continue
        rule, result = max(firing, key=lambda pair: pair[0].threshold)
        previous = issued_before.get(parameter)
        if previous is not None and rule.threshold <= previous:
            continue
        message = render_message(rule, result.value)
        tasks = tasks_in_window(db, farm_id, rule, now)
        if tasks:
            message = f"{message} {tasks_sentence(tasks)}"
        alert = WeatherAlert(
            rule_id=rule.rule_id,
            farm_id=farm_id,
            weather_id=result.slot.weather_id,
            activity_id=tasks[0][0] if tasks else None,
            message=message,
            severity=rule.severity,
            issued_at=now,
        )
        issued.append((rule, alert))

    if not issued:
        return []
    db.add_all(alert for _, alert in issued)
    db.flush()
    members = _active_member_ids(db, farm_id)
    db.add_all(
        Notification(
            user_id=user_id,
            farm_id=farm_id,
            alert_id=alert.alert_id,
            type=NotificationType.WEATHER_ALERT,
            title=rule.rule_name,
            body=alert.message,
            severity=alert.severity,
            created_at=now,
        )
        for rule, alert in issued
        for user_id in members
    )
    return [alert for _, alert in issued]


def evaluate_after_fetch(
    farm_id: int, session_factory: Callable[[], Session] = SessionLocal
) -> int | None:
    """Evaluate one farm in its own transaction right after its fetch was saved. Never
    raises: a failure is logged by error type and the fetch still counts as done. Returns
    the number of alerts issued, or None when the evaluation failed."""
    try:
        with session_factory() as db:
            issued = evaluate_farm(db, farm_id)
            db.commit()
            return len(issued)
    except Exception as exc:  # an alert problem must never break the fetch
        logger.error("Alert evaluation failed for farm %s: %s", farm_id, type(exc).__name__)
        return None


@dataclass
class EvaluationSummary:
    """Alerts issued per evaluated farm, and the farms whose evaluation failed."""

    issued: dict[int, int]
    failed: list[int]


def evaluate_farms(
    farm_ids: Iterable[int] | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> EvaluationSummary:
    """Evaluate the given farms (every farm when None) on their stored forecasts, without
    fetching. Unknown IDs are ignored."""
    with session_factory() as db:
        query = select(Farm.farm_id).order_by(Farm.farm_id)
        if farm_ids is not None:
            query = query.where(Farm.farm_id.in_(list(farm_ids)))
        ids = list(db.scalars(query))
    summary = EvaluationSummary(issued={}, failed=[])
    for farm_id in ids:
        issued = evaluate_after_fetch(farm_id, session_factory)
        if issued is None:
            summary.failed.append(farm_id)
        else:
            summary.issued[farm_id] = issued
    return summary
