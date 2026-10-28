from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.enums import AccountStatus, UserRole
from app.schemas.auth import Email, MobileNo, Municipality, Name, Password


class AdminCreate(BaseModel):
    """Input for the create-admin command; same field rules as sign-up."""

    first_name: Name
    last_name: Name
    mobile_no: MobileNo
    email: Email | None = None
    password: Password
    municipality: Municipality


class UserStatusUpdate(BaseModel):
    """PATCH /admin/users/{user_id}/status body: approve ('active') or deactivate."""

    model_config = ConfigDict(extra="forbid")

    account_status: Literal["active", "deactivated"]


class UserStatusResponse(BaseModel):
    user_id: int
    account_status: AccountStatus


class AdminUserItem(BaseModel):
    """GET /admin/users item (Section 6)."""

    user_id: int
    first_name: str
    last_name: str
    mobile_no: str
    email: str | None
    member_no: str | None
    municipality: str
    barangay_name: str | None
    role: UserRole
    account_status: AccountStatus
    created_at: datetime
    deletion_requested_at: datetime | None
