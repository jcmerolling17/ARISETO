"""Native PostgreSQL enum types (Section 4), named as in the data dictionary."""

import enum

from sqlalchemy import Enum


class UserRole(enum.StrEnum):
    MEMBER = "member"
    COOP_ADMIN = "coop_admin"


class LanguageCode(enum.StrEnum):
    FIL = "fil"
    EN = "en"


class AccountStatus(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


class FarmRole(enum.StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"
    TENANT = "tenant"
    WORKER = "worker"


class MaturityClass(enum.StrEnum):
    VERY_EARLY = "very_early"
    EARLY = "early"
    MEDIUM = "medium"
    LATE = "late"


class CropSeason(enum.StrEnum):
    WET = "wet"
    DRY = "dry"


class CycleStatus(enum.StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    HARVESTED = "harvested"
    FAILED = "failed"


class TaskType(enum.StrEnum):
    LAND_PREP = "land_prep"
    PLANTING = "planting"
    FERTILIZATION = "fertilization"
    IRRIGATION = "irrigation"
    PEST_CONTROL = "pest_control"
    WEEDING = "weeding"
    HARVEST = "harvest"
    OTHER = "other"


class ActivityStatus(enum.StrEnum):
    PENDING = "pending"
    DONE = "done"
    SKIPPED = "skipped"
    RESCHEDULED = "rescheduled"


class QuantityUnit(enum.StrEnum):
    """EXPENSE.unit: required when a quantity is given."""

    KG = "kg"
    SACK = "sack"
    LITER = "liter"
    BAG = "bag"
    HOUR = "hour"


class AlertParameter(enum.StrEnum):
    """ALERT_RULE.parameter: the WEATHER_LOG reading a rule checks; heat_index_c is
    computed for each slot from temp_c and humidity_pct."""

    TEMP_C = "temp_c"
    FEELS_LIKE_C = "feels_like_c"
    HUMIDITY_PCT = "humidity_pct"
    RAIN_MM = "rain_mm"
    PRECIP_PROBABILITY_PCT = "precip_probability_pct"
    WIND_SPEED_MPS = "wind_speed_mps"
    HEAT_INDEX_C = "heat_index_c"


class AlertOperator(enum.StrEnum):
    GT = ">"
    GE = ">="
    LT = "<"
    LE = "<="


class AlertSeverity(enum.StrEnum):
    """Shared by ALERT_RULE, WEATHER_ALERT and NOTIFICATION."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertAggregation(enum.StrEnum):
    """How the forecast slots in a rule's window are combined."""

    SUM = "sum"
    MAX = "max"


class NotificationType(enum.StrEnum):
    """NOTIFICATION.type (Prototype Review decision 21); Phase 8 creates only weather_alert."""

    WEATHER_ALERT = "weather_alert"
    TASK_REMINDER = "task_reminder"
    GROWTH_STAGE = "growth_stage"
    YIELD_UPDATE = "yield_update"
    DISEASE_DETECTED = "disease_detected"


def pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """A named PostgreSQL enum storing the members' lowercase values."""
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


user_role = pg_enum(UserRole, "user_role")
language_code = pg_enum(LanguageCode, "language_code")
account_status = pg_enum(AccountStatus, "account_status")
farm_role = pg_enum(FarmRole, "farm_role")
maturity_class = pg_enum(MaturityClass, "maturity_class")
crop_season = pg_enum(CropSeason, "crop_season")
cycle_status = pg_enum(CycleStatus, "cycle_status")
task_type = pg_enum(TaskType, "task_type")
activity_status = pg_enum(ActivityStatus, "activity_status")
quantity_unit = pg_enum(QuantityUnit, "quantity_unit")
alert_parameter = pg_enum(AlertParameter, "alert_parameter")
alert_operator = pg_enum(AlertOperator, "alert_operator")
alert_severity = pg_enum(AlertSeverity, "alert_severity")
alert_aggregation = pg_enum(AlertAggregation, "alert_aggregation")
notification_type = pg_enum(NotificationType, "notification_type")
