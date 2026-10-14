from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.barangay import BarangayOut
from app.services import barangay_service

router = APIRouter(tags=["barangays"])


@router.get("/barangays", response_model=list[BarangayOut])
def list_barangays(
    municipality: str = Query(..., description="One of the 11 Occidental Mindoro municipalities"),
    db: Session = Depends(get_db),
) -> list[BarangayOut]:
    """Barangays in a municipality (public; used during sign-up). Empty until seeded.

    Errors: 422 unknown_municipality.
    """
    rows = barangay_service.list_barangays(db, municipality)
    return [BarangayOut.model_validate(row) for row in rows]
