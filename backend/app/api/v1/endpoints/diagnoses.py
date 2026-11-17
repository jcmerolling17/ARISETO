from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models import User
from app.schemas.diagnosis import DiagnosisItem, DiagnosisOut
from app.services import diagnosis_service, disease_model
from app.services.disease_model import Predictor

router = APIRouter(tags=["diagnoses"])


def get_predictor() -> Predictor:
    """The loaded disease model; 503 model_unavailable when none is loaded."""
    predictor = disease_model.current().predictor
    if predictor is None:
        raise AppError(503, "model_unavailable")
    return predictor


@router.post("/diagnoses", status_code=status.HTTP_201_CREATED, response_model=DiagnosisOut)
def create_diagnosis(
    image: UploadFile = File(...),
    cycle_id: int | None = Form(None),
    crop_id: int | None = Form(None),
    user: User = Depends(require_active_user),
    predictor: Predictor = Depends(get_predictor),
    db: Session = Depends(get_db),
) -> DiagnosisOut:
    """Scan a leaf photo (JPEG or PNG, at most 5 MB, at least 224 x 224 px). The crop comes
    from cycle_id (the chosen field's current crop cycle) or crop_id when no field is chosen.
    Every result is saved with its photo before it is returned, unrecognized included.

    Errors: 404 cycle_not_found; 413 image_too_large; 415 unsupported_image_type;
    422 crop_required, crop_not_found, crop_mismatch, image_too_small, image_unreadable;
    503 model_unavailable (nothing is saved).
    """
    data = image.file.read(diagnosis_service.MAX_IMAGE_BYTES + 1)
    return diagnosis_service.create_diagnosis(db, user, predictor, data, cycle_id, crop_id)


@router.get("/diagnoses", response_model=list[DiagnosisItem])
def list_diagnoses(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> list[DiagnosisItem]:
    """The caller's own scans, newest first."""
    return diagnosis_service.list_diagnoses(db, user, limit, offset)


@router.get("/diagnoses/{diagnosis_id}", response_model=DiagnosisOut)
def get_diagnosis(
    diagnosis_id: int,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> DiagnosisOut:
    """One of the caller's scans, with the disease text as it is now.

    Errors: 404 diagnosis_not_found, also for another user's scan.
    """
    return diagnosis_service.get_diagnosis(db, user, diagnosis_id)


@router.get(
    "/diagnoses/{diagnosis_id}/image",
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
)
def get_diagnosis_image(
    diagnosis_id: int,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """The stored photo of one of the caller's scans.

    Errors: 404 diagnosis_not_found (also for another user's scan), image_missing.
    """
    path, media_type = diagnosis_service.image_file(db, user, diagnosis_id)
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private"})
