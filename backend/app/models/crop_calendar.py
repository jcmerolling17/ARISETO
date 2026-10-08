import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ActivityStatus, TaskType, activity_status, task_type


class CalendarTemplateTask(Base):
    """CALENDAR_TEMPLATE_TASK: admin-maintained week-by-week tasks per variety."""

    __tablename__ = "calendar_template_task"

    template_task_id: Mapped[int] = mapped_column(
        Integer, Identity(always=True), primary_key=True
    )
    variety_id: Mapped[int] = mapped_column(ForeignKey("crop_variety.variety_id"))
    week_no: Mapped[int] = mapped_column(SmallInteger)
    task_type: Mapped[TaskType] = mapped_column(task_type)
    task_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_weather_sensitive: Mapped[bool] = mapped_column(Boolean)


class CropActivity(Base):
    """CROP_ACTIVITY: a scheduled task; client_uuid makes offline sync idempotent."""

    __tablename__ = "crop_activity"

    activity_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("crop_cycle.cycle_id"))
    template_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("calendar_template_task.template_task_id")
    )
    title: Mapped[str] = mapped_column(String(100))
    scheduled_date: Mapped[date] = mapped_column(Date)
    status: Mapped[ActivityStatus] = mapped_column(
        activity_status, server_default=ActivityStatus.PENDING.value
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_uuid: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
