from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import (
    AlertAggregation,
    AlertOperator,
    AlertParameter,
    AlertSeverity,
    NotificationType,
    TaskType,
    alert_aggregation,
    alert_operator,
    alert_parameter,
    alert_severity,
    notification_type,
    task_type,
)


class AlertRule(Base):
    """ALERT_RULE (Table 19): an administrator-defined weather rule; the seven seeded rules
    use PAGASA's published levels."""

    __tablename__ = "alert_rule"
    __table_args__ = (
        CheckConstraint("threshold > 0", name="threshold_positive"),
        CheckConstraint("lookahead_hours > 0", name="lookahead_hours_positive"),
    )

    rule_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    rule_name: Mapped[str] = mapped_column(String(100))
    parameter: Mapped[AlertParameter] = mapped_column(alert_parameter)
    operator: Mapped[AlertOperator] = mapped_column(alert_operator)
    threshold: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    lookahead_hours: Mapped[int] = mapped_column(SmallInteger)
    affected_task_type: Mapped[TaskType | None] = mapped_column(task_type)
    message_template: Mapped[str] = mapped_column(Text)
    severity: Mapped[AlertSeverity] = mapped_column(alert_severity)
    aggregation: Mapped[AlertAggregation] = mapped_column(alert_aggregation)
    source_reference: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean)


class WeatherAlert(Base):
    """WEATHER_ALERT (Table 20): one issued alert; never issued twice for the same rule,
    farm and forecast slot."""

    __tablename__ = "weather_alert"
    __table_args__ = (UniqueConstraint("rule_id", "farm_id", "weather_id"),)

    alert_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rule.rule_id"))
    farm_id: Mapped[int] = mapped_column(ForeignKey("farm.farm_id"))
    weather_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("weather_log.weather_id"))
    # NULL until the crop calendar links alerts to weather-sensitive tasks.
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("crop_activity.activity_id"))
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[AlertSeverity] = mapped_column(alert_severity)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    """NOTIFICATION (Table 24): one in-app notification for one member. alert_id is set
    exactly for a weather_alert, activity_id exactly for a task_reminder."""

    __tablename__ = "notification"
    __table_args__ = (
        UniqueConstraint("user_id", "alert_id"),
        CheckConstraint(
            "(type = 'weather_alert') = (alert_id IS NOT NULL)", name="alert_id_with_type"
        ),
        CheckConstraint(
            "(type = 'task_reminder') = (activity_id IS NOT NULL)", name="activity_id_with_type"
        ),
        Index("ix_notification_user_id_created_at", "user_id", "created_at"),
    )

    notification_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    farm_id: Mapped[int | None] = mapped_column(ForeignKey("farm.farm_id"))
    alert_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("weather_alert.alert_id"))
    # The task a task_reminder is about (Phase 7).
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("crop_activity.activity_id"))
    type: Mapped[NotificationType] = mapped_column(notification_type)
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    severity: Mapped[AlertSeverity | None] = mapped_column(alert_severity)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
