from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AccountStatus, LanguageCode, UserRole
from app.schemas.auth import Email, MobileNo, Name, Password


class UserMe(BaseModel):
    """GET /users/me body, also returned by PATCH /users/me (Section 6)."""

    user_id: int
    first_name: str
    last_name: str
    mobile_no: str
    email: str | None
    member_no: str | None
    municipality: str
    barangay_id: int | None
    barangay_name: str | None
    preferred_language: LanguageCode
    role: UserRole
    account_status: AccountStatus
    created_at: datetime
    deletion_requested_at: datetime | None


# Fields that must keep a value: sending null for them is a 422. email may be null (cleared).
_NOT_NULL = ("first_name", "last_name", "mobile_no", "preferred_language")


class UserUpdate(BaseModel):
    """PATCH /users/me body: any of these fields; values are normalized as at sign-up.
    current_password is needed when mobile_no or email changes, since they are login IDs."""

    model_config = ConfigDict(extra="forbid")

    first_name: Name | None = None
    last_name: Name | None = None
    email: Email | None = None
    mobile_no: MobileNo | None = None
    preferred_language: LanguageCode | None = None
    current_password: str | None = None

    @model_validator(mode="after")
    def _required_fields_are_not_null(self) -> "UserUpdate":
        for name in _NOT_NULL:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    def changes(self) -> dict:
        """The profile fields the request sent, without current_password."""
        return self.model_dump(include=self.model_fields_set - {"current_password"})


class PasswordChange(BaseModel):
    """POST /users/me/password body."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1)
    new_password: Password


class PasswordChanged(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class DeletionRequested(BaseModel):
    deletion_requested_at: datetime
