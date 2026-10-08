from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.constants import MIN_PASSWORD_LENGTH, MOBILE_PATTERN, MUNICIPALITIES
from app.models.enums import AccountStatus, LanguageCode, UserRole


def _collapse_spaces(value: str) -> str:
    return " ".join(value.split())


def _lowercase(value: str | None) -> str | None:
    return value.lower() if value is not None else None


def _known_municipality(value: str) -> str:
    if value not in MUNICIPALITIES:
        raise ValueError("must be one of the 11 Occidental Mindoro municipalities")
    return value


Name = Annotated[
    str, AfterValidator(_collapse_spaces), StringConstraints(min_length=1, max_length=60)
]
MobileNo = Annotated[str, StringConstraints(pattern=MOBILE_PATTERN)]
Password = Annotated[str, StringConstraints(min_length=MIN_PASSWORD_LENGTH, max_length=128)]
MemberNo = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=20)
]
Email = Annotated[EmailStr, StringConstraints(max_length=120), AfterValidator(_lowercase)]
Municipality = Annotated[str, AfterValidator(_known_municipality)]


class RegisterRequest(BaseModel):
    """POST /auth/register body (Section 6)."""

    model_config = ConfigDict(extra="forbid")

    first_name: Name
    last_name: Name
    mobile_no: MobileNo
    email: Email | None = None
    password: Password
    member_no: MemberNo
    municipality: Municipality
    barangay_id: int | None = None
    preferred_language: LanguageCode = LanguageCode.FIL


class RegisterResponse(BaseModel):
    user_id: int
    account_status: AccountStatus


class LoginRequest(BaseModel):
    """POST /auth/login body: mobile_no or email, plus password."""

    model_config = ConfigDict(extra="forbid")

    mobile_no: str | None = None
    email: Annotated[str | None, AfterValidator(_lowercase)] = None
    password: str = Field(min_length=1)

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> "LoginRequest":
        if (self.mobile_no is None) == (self.email is None):
            raise ValueError("send exactly one of mobile_no or email")
        return self


class LoginUser(BaseModel):
    user_id: int
    first_name: str
    role: UserRole


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: LoginUser
