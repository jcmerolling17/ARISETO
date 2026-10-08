from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Identity, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MOBILE_PATTERN, MUNICIPALITIES, sql_in_list
from app.db.base import Base
from app.models.enums import (
    AccountStatus,
    LanguageCode,
    UserRole,
    account_status,
    language_code,
    user_role,
)


class User(Base):
    """USER (physical table: users, since "user" is reserved in PostgreSQL)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"mobile_no ~ '{MOBILE_PATTERN}'", name="mobile_no_format"),
        CheckConstraint(
            "role <> 'member' OR member_no IS NOT NULL", name="member_no_required_for_member"
        ),
        CheckConstraint(f"municipality IN {sql_in_list(MUNICIPALITIES)}", name="municipality"),
    )

    user_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    member_no: Mapped[str | None] = mapped_column(String(20), unique=True)
    first_name: Mapped[str] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60))
    mobile_no: Mapped[str] = mapped_column(String(13), unique=True)
    email: Mapped[str | None] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(user_role, server_default=UserRole.MEMBER.value)
    barangay_id: Mapped[int | None] = mapped_column(ForeignKey("barangay.barangay_id"))
    municipality: Mapped[str] = mapped_column(String(80))
    preferred_language: Mapped[LanguageCode] = mapped_column(
        language_code, server_default=LanguageCode.FIL.value
    )
    account_status: Mapped[AccountStatus] = mapped_column(
        account_status, server_default=AccountStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
