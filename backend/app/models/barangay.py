from decimal import Decimal

from sqlalchemy import CheckConstraint, Identity, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MUNICIPALITIES, sql_in_list
from app.db.base import Base


class Barangay(Base):
    """BARANGAY: read-only lookup seeded from the PSGC; supplies center coordinates."""

    __tablename__ = "barangay"
    __table_args__ = (
        UniqueConstraint("municipality", "barangay_name"),
        CheckConstraint(f"municipality IN {sql_in_list(MUNICIPALITIES)}", name="municipality"),
    )

    barangay_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    psgc_code: Mapped[str] = mapped_column(String(10), unique=True)
    municipality: Mapped[str] = mapped_column(String(80))
    barangay_name: Mapped[str] = mapped_column(String(100))
    center_latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    center_longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
