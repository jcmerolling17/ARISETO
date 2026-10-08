"""BARANGAY lookup (read-only)."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import MUNICIPALITIES
from app.core.errors import AppError
from app.models import Barangay


def list_barangays(db: Session, municipality: str) -> Sequence[Barangay]:
    """Barangays of one of the 11 municipalities, alphabetically; empty until the table is
    seeded."""
    if municipality not in MUNICIPALITIES:
        raise AppError(422, "unknown_municipality")
    return db.scalars(
        select(Barangay)
        .where(Barangay.municipality == municipality)
        .order_by(Barangay.barangay_name)
    ).all()
