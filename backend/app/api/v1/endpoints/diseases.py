from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.db.session import get_db
from app.models import User
from app.schemas.diagnosis import DiseaseSummary
from app.services import disease_service

router = APIRouter(tags=["diseases"])


@router.get("/diseases", response_model=list[DiseaseSummary])
def list_diseases(
    crop_id: int | None = None,
    _user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> list[DiseaseSummary]:
    """The disease knowledge base with each disease's number of treatment steps; empty until
    it is imported.

    Errors: 422 crop_not_found.
    """
    return disease_service.list_diseases(db, crop_id)
