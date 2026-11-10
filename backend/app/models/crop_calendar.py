import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import (
    ActivityStatus,
    CalendarAnchor,
    GrowthStage,
    TaskType,
    activity_status,
    calendar_anchor,
    growth_stage,
    task_type,
)


class CalendarTemplateTask(Base):
    """CALENDAR_TEMPLATE_TASK (Table 9): one task of a variety's schedule, timed in days from
    sowing or from harvest; loaded from app/seeds/calendar_templates.csv by the seed command.
    A repeating task has all three repeat columns; a range has day_offset_end."""

    __tablename__ = "calendar_template_task"
    __table_args__ = (
        CheckConstraint(
            "day_offset_end IS NULL OR day_offset_end >= day_offset", name="day_offset_end_order"
        ),
        CheckConstraint(
            "(repeat_every_days IS NULL) = (repeat_until_anchor IS NULL) "
            "AND (repeat_every_days IS NULL) = (repeat_until_offset IS NULL)",
            name="repeat_columns_together",
        ),
        CheckConstraint(
            "repeat_every_days IS NULL OR repeat_every_days > 0", name="repeat_every_days_positive"
        ),
        # The seed matches rows on these, so running it again updates instead of adding.
        UniqueConstraint("variety_id", "anchor", "day_offset", "task_name"),
    )

    template_task_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    variety_id: Mapped[int] = mapped_column(ForeignKey("crop_variety.variety_id"))
    anchor: Mapped[CalendarAnchor] = mapped_column(calendar_anchor)
    day_offset: Mapped[int] = mapped_column(SmallInteger)
    day_offset_end: Mapped[int | None] = mapped_column(SmallInteger)
    repeat_every_days: Mapped[int | None] = mapped_column(SmallInteger)
    repeat_until_anchor: Mapped[CalendarAnchor | None] = mapped_column(calendar_anchor)
    repeat_until_offset: Mapped[int | None] = mapped_column(SmallInteger)
    growth_stage: Mapped[GrowthStage] = mapped_column(growth_stage)
    source_reference: Mapped[str] = mapped_column(String(255))
    task_type: Mapped[TaskType] = mapped_column(task_type)
    task_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_weather_sensitive: Mapped[bool] = mapped_column(Boolean)


class CropActivity(Base):
    """CROP_ACTIVITY (Table 10): one scheduled task, generated from a template or added by a
    member (template_task_id NULL); client_uuid makes offline sync idempotent."""

    __tablename__ = "crop_activity"
    __table_args__ = (
        CheckConstraint("end_date IS NULL OR end_date >= scheduled_date", name="end_date_order"),
    )

    activity_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("crop_cycle.cycle_id"))
    template_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("calendar_template_task.template_task_id")
    )
    title: Mapped[str] = mapped_column(String(100))
    scheduled_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    scheduled_time: Mapped[time | None] = mapped_column(Time)
    reminder: Mapped[bool] = mapped_column(Boolean, server_default="false")
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(500))
    task_type: Mapped[TaskType] = mapped_column(task_type, server_default=TaskType.OTHER.value)
    growth_stage: Mapped[GrowthStage | None] = mapped_column(growth_stage)
    is_weather_sensitive: Mapped[bool] = mapped_column(Boolean, server_default="false")
    status: Mapped[ActivityStatus] = mapped_column(
        activity_status, server_default=ActivityStatus.PENDING.value
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_uuid: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
