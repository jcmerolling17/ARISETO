import uuid
from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    model_validator,
)

from app.models.enums import ActivityStatus, CropSeason, CycleStatus, GrowthStage, TaskType


def _collapse(value: str | None) -> str | None:
    """Trim and collapse spaces; a blank value becomes None."""
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def _required_title(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("title may not be blank")
    return value


# CROP_ACTIVITY.title varchar(100) and notes varchar(500).
Title = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_required_title)]
Notes = Annotated[str | None, Field(max_length=500), AfterValidator(_collapse)]


class ActivityItem(BaseModel):
    """One CROP_ACTIVITY row as the activity endpoints return it (Section 6). description
    and source_reference come from the template; a custom task has neither."""

    activity_id: int
    title: str
    description: str | None
    source_reference: str | None
    task_type: TaskType
    growth_stage: GrowthStage | None
    scheduled_date: date
    end_date: date | None
    scheduled_time: time | None
    reminder: bool
    notes: str | None
    status: ActivityStatus
    completed_at: datetime | None
    is_weather_sensitive: bool
    is_custom: bool


class FarmActivityItem(ActivityItem):
    cycle_id: int
    field_name: str


class CycleCalendar(BaseModel):
    """completion_pct is (done + skipped) ÷ all tasks × 100, rounded; 0 with no tasks."""

    cycle_id: int
    field_name: str
    crop_name: str
    variety_name: str
    season: CropSeason
    planting_date: date
    expected_harvest_date: date
    status: CycleStatus
    completion_pct: int


class CycleActivities(BaseModel):
    cycle: CycleCalendar
    items: list[ActivityItem]


class FarmActivities(BaseModel):
    items: list[FarmActivityItem]


class ActivityCreate(BaseModel):
    """POST /cycles/{cycle_id}/activities body: a custom task."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    scheduled_date: date
    scheduled_time: time | None = None
    reminder: StrictBool = False
    notes: Notes = None
    growth_stage: GrowthStage | None = None
    client_uuid: uuid.UUID


class ActivityUpdate(BaseModel):
    """PATCH /activities/{activity_id} body: any of these. A new date or time is a
    reschedule; title and growth_stage are for custom tasks only (422 not_editable).
    scheduled_time, notes and growth_stage may be cleared with null; the others may not."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "done", "skipped"] | None = None
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    reminder: StrictBool | None = None
    notes: Notes = None
    title: Title | None = None
    growth_stage: GrowthStage | None = None

    @model_validator(mode="after")
    def _required_not_null(self) -> "ActivityUpdate":
        for name in ("status", "scheduled_date", "reminder", "title"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} may not be null or blank")
        return self
