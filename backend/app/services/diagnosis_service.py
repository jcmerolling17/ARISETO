"""Disease detection scans (DFD 3.1-3.8; Section 6, POST and GET /diagnoses).

A scan is checked (crop, then the photo), run through the model, and saved before anything
is shown: the photo goes to LEAF_IMAGE_DIR and the DIAGNOSIS row to the database together, so
an unrecognized photo reaches the history too. If the row can't be saved, the photo is removed.
"""

from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.seasons import philippine_today
from app.models import (
    Crop,
    CropCycle,
    CropVariety,
    Diagnosis,
    Disease,
    FarmAssignment,
    FarmField,
    Treatment,
    User,
)
from app.models.enums import ResultStatus
from app.schemas.diagnosis import DiagnosisItem, DiagnosisOut, DiseaseInfo, TreatmentOut
from app.services.disease_model import Prediction, Predictor

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MIN_IMAGE_SIDE = 224
# File signatures; the extension and the content type sent by the phone are not trusted.
_SIGNATURES = {b"\xff\xd8\xff": "jpg", b"\x89PNG\r\n\x1a\n": "png"}
MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png"}


@dataclass(frozen=True)
class CheckedImage:
    data: bytes
    extension: str
    image: Image.Image


def check_image(data: bytes) -> CheckedImage:
    """A JPEG or PNG of at most 5 MB, at least 224 x 224 px, upright and in RGB.

    Errors: 413 image_too_large; 415 unsupported_image_type; 422 image_unreadable,
    image_too_small.
    """
    if len(data) > MAX_IMAGE_BYTES:
        raise AppError(413, "image_too_large")
    extension = next((ext for sig, ext in _SIGNATURES.items() if data.startswith(sig)), None)
    if extension is None:
        raise AppError(415, "unsupported_image_type")
    try:
        image = Image.open(BytesIO(data))
        image.load()
        # Phone cameras store the rotation in EXIF; turn the pixels to match.
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as exc:  # truncated, corrupt, or too large to decode safely
        raise AppError(422, "image_unreadable") from exc
    if min(image.size) < MIN_IMAGE_SIDE:
        raise AppError(422, "image_too_small")
    return CheckedImage(data, extension, image)


def _member_cycle(db: Session, user: User, cycle_id: int) -> tuple[CropCycle, int]:
    """The cycle and its crop_id, for a member of the cycle's farm; 404 cycle_not_found
    otherwise, so the answer never reveals which cycles exist."""
    row = db.execute(
        select(CropCycle, CropVariety.crop_id)
        .join(CropVariety, CropVariety.variety_id == CropCycle.variety_id)
        .join(FarmField, FarmField.field_id == CropCycle.field_id)
        .join(
            FarmAssignment,
            (FarmAssignment.farm_id == FarmField.farm_id)
            & (FarmAssignment.user_id == user.user_id),
        )
        .where(CropCycle.cycle_id == cycle_id)
    ).first()
    if row is None:
        raise AppError(404, "cycle_not_found")
    return row[0], row[1]


def resolve_crop(
    db: Session, user: User, cycle_id: int | None, crop_id: int | None
) -> tuple[Crop, int | None]:
    """The scanned crop: from the chosen field's crop cycle (decision 1), or crop_id when no
    field is chosen. When both are sent they must match.

    Errors: 404 cycle_not_found; 422 crop_required, crop_not_found, crop_mismatch.
    """
    if cycle_id is not None:
        _cycle, cycle_crop_id = _member_cycle(db, user, cycle_id)
        if crop_id is not None and crop_id != cycle_crop_id:
            raise AppError(422, "crop_mismatch")
        return db.get(Crop, cycle_crop_id), cycle_id
    if crop_id is None:
        raise AppError(422, "crop_required")
    crop = db.get(Crop, crop_id)
    if crop is None:
        raise AppError(422, "crop_not_found")
    return crop, None


def classify(
    db: Session, crop: Crop, prediction: Prediction, threshold: float
) -> tuple[ResultStatus, Disease | None]:
    """Section 6 result rules, the threshold first: below it the result is 'unrecognized'
    (a healthy label too); the crop's <crop>_healthy class is 'healthy'; a label of another
    crop, or one with no DISEASE row, is 'unrecognized'; otherwise 'diseased'."""
    crop_key = crop.crop_name.lower()
    if prediction.confidence < threshold:
        return ResultStatus.UNRECOGNIZED, None
    if prediction.label == f"{crop_key}_healthy":
        return ResultStatus.HEALTHY, None
    if not prediction.label.startswith(f"{crop_key}_"):
        return ResultStatus.UNRECOGNIZED, None
    disease = db.scalar(select(Disease).where(Disease.model_class_label == prediction.label))
    if disease is None or disease.crop_id != crop.crop_id:
        return ResultStatus.UNRECOGNIZED, None
    return ResultStatus.DISEASED, disease


def _leaf_dir() -> Path:
    return get_settings().leaf_image_dir


def create_diagnosis(
    db: Session,
    user: User,
    predictor: Predictor,
    data: bytes,
    cycle_id: int | None,
    crop_id: int | None,
) -> DiagnosisOut:
    crop, cycle_id = resolve_crop(db, user, cycle_id, crop_id)
    checked = check_image(data)
    prediction = predictor.predict(checked.image)
    status, disease = classify(db, crop, prediction, predictor.threshold)

    diagnosis = Diagnosis(
        user_id=user.user_id,
        crop_id=crop.crop_id,
        cycle_id=cycle_id,
        disease_id=disease.disease_id if disease else None,
        image_path="",
        predicted_label=prediction.label,
        confidence=Decimal(str(round(prediction.confidence, 4))),
        result_status=status,
        model_version=predictor.version,
    )
    db.add(diagnosis)
    photo: Path | None = None
    try:
        db.flush()  # gives diagnosis_id, which names the photo
        today = philippine_today()
        diagnosis.image_path = (
            f"leaf/{today:%Y}/{today:%m}/{diagnosis.diagnosis_id}.{checked.extension}"
        )
        photo = _leaf_dir() / diagnosis.image_path
        photo.parent.mkdir(parents=True, exist_ok=True)
        photo.write_bytes(checked.data)
        db.commit()
    except BaseException:
        db.rollback()
        if photo is not None:
            photo.unlink(missing_ok=True)
        raise
    db.refresh(diagnosis)
    return _out(db, diagnosis)


def _disease_info(db: Session, disease: Disease) -> DiseaseInfo:
    steps = db.scalars(
        select(Treatment)
        .where(Treatment.disease_id == disease.disease_id)
        .order_by(Treatment.step_no)
    )
    return DiseaseInfo(
        disease_id=disease.disease_id,
        disease_name=disease.disease_name,
        local_name=disease.local_name,
        pathogen_type=disease.pathogen_type,
        symptoms=disease.symptoms,
        description_en=disease.description_en,
        description_fil=disease.description_fil,
        impact_en=disease.impact_en,
        impact_fil=disease.impact_fil,
        treatments=[
            TreatmentOut(
                step_no=step.step_no,
                treatment_type=step.treatment_type,
                instruction_en=step.instruction_en,
                instruction_fil=step.instruction_fil,
                source_reference=step.source_reference,
            )
            for step in steps
        ],
    )


def _out(db: Session, diagnosis: Diagnosis) -> DiagnosisOut:
    disease = db.get(Disease, diagnosis.disease_id) if diagnosis.disease_id else None
    return DiagnosisOut(
        diagnosis_id=diagnosis.diagnosis_id,
        result_status=diagnosis.result_status,
        confidence=float(diagnosis.confidence),
        crop_name=db.get(Crop, diagnosis.crop_id).crop_name,
        disease=_disease_info(db, disease) if disease else None,
        model_version=diagnosis.model_version,
        created_at=diagnosis.created_at,
    )


def _own_diagnosis(db: Session, user: User, diagnosis_id: int) -> Diagnosis:
    """The caller's own scan; 404 diagnosis_not_found otherwise, also for another user's."""
    diagnosis = db.get(Diagnosis, diagnosis_id)
    if diagnosis is None or diagnosis.user_id != user.user_id:
        raise AppError(404, "diagnosis_not_found")
    return diagnosis


def get_diagnosis(db: Session, user: User, diagnosis_id: int) -> DiagnosisOut:
    """A saved scan, with the disease text as it is now in the knowledge base."""
    return _out(db, _own_diagnosis(db, user, diagnosis_id))


def image_file(db: Session, user: User, diagnosis_id: int) -> tuple[Path, str]:
    """The stored photo and its media type. Errors: 404 diagnosis_not_found, image_missing."""
    diagnosis = _own_diagnosis(db, user, diagnosis_id)
    root = _leaf_dir().resolve()
    path = (root / diagnosis.image_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise AppError(404, "image_missing")
    return path, MEDIA_TYPES.get(path.suffix.lstrip(".").lower(), "application/octet-stream")


def list_diagnoses(db: Session, user: User, limit: int, offset: int) -> list[DiagnosisItem]:
    """The caller's own scans, newest first."""
    rows = db.execute(
        select(Diagnosis, Crop.crop_name, FarmField.field_name, Disease)
        .join(Crop, Crop.crop_id == Diagnosis.crop_id)
        .outerjoin(CropCycle, CropCycle.cycle_id == Diagnosis.cycle_id)
        .outerjoin(FarmField, FarmField.field_id == CropCycle.field_id)
        .outerjoin(Disease, Disease.disease_id == Diagnosis.disease_id)
        .where(Diagnosis.user_id == user.user_id)
        .order_by(Diagnosis.created_at.desc(), Diagnosis.diagnosis_id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        DiagnosisItem(
            diagnosis_id=diagnosis.diagnosis_id,
            created_at=diagnosis.created_at,
            crop_name=crop_name,
            field_name=field_name,
            result_status=diagnosis.result_status,
            disease_name=disease.disease_name if disease else None,
            local_name=disease.local_name if disease else None,
            confidence=float(diagnosis.confidence),
        )
        for diagnosis, crop_name, field_name, disease in rows
    ]
