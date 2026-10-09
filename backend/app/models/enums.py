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


class PlantingMethod(enum.StrEnum):
    TRANSPLANTING = "transplanting"
    DIRECT_SEEDING = "direct_seeding"


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
planting_method = pg_enum(PlantingMethod, "planting_method")
task_type = pg_enum(TaskType, "task_type")
activity_status = pg_enum(ActivityStatus, "activity_status")
