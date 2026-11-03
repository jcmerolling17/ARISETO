from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import AlertSeverity, NotificationType


class NotificationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: int
    type: NotificationType
    title: str
    body: str
    severity: AlertSeverity | None
    farm_id: int | None
    created_at: datetime
    read_at: datetime | None


class NotificationList(BaseModel):
    """unread_count counts all of the caller's unread notifications, whatever the filters."""

    unread_count: int
    items: list[NotificationItem]


class NotificationRead(BaseModel):
    notification_id: int
    read_at: datetime


class ReadAllResult(BaseModel):
    updated: int
