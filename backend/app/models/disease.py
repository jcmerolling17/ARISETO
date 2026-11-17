from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import (
    PathogenType,
    ResultStatus,
    TreatmentType,
    pathogen_type,
    result_status,
    treatment_type,
)


class Disease(Base):
    """DISEASE (Table 11): a disease or pest condition the model can name. Loaded from the
    team's CSV files by import-diseases; model_class_label matches a class the CNN outputs."""

    __tablename__ = "disease"

    disease_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    crop_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("crop.crop_id"))
    disease_name: Mapped[str] = mapped_column(String(100))
    local_name: Mapped[str | None] = mapped_column(String(100))
    model_class_label: Mapped[str] = mapped_column(String(80), unique=True)
    pathogen_type: Mapped[PathogenType] = mapped_column(pathogen_type)
    # One visible symptom per line; shown as the Warning Signs list.
    symptoms: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    description_fil: Mapped[str | None] = mapped_column(Text)
    impact_en: Mapped[str | None] = mapped_column(Text)
    impact_fil: Mapped[str | None] = mapped_column(Text)


class Treatment(Base):
    """TREATMENT (Table 12): one ordered step of a disease's treatment, with its source."""

    __tablename__ = "treatment"
    __table_args__ = (
        CheckConstraint("step_no > 0", name="step_no_positive"),
        UniqueConstraint("disease_id", "step_no"),
    )

    treatment_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    disease_id: Mapped[int] = mapped_column(ForeignKey("disease.disease_id"))
    step_no: Mapped[int] = mapped_column(SmallInteger)
    treatment_type: Mapped[TreatmentType] = mapped_column(treatment_type)
    instruction_en: Mapped[str] = mapped_column(Text)
    instruction_fil: Mapped[str | None] = mapped_column(Text)
    source_reference: Mapped[str] = mapped_column(String(255))


class Diagnosis(Base):
    """DIAGNOSIS (Table 13): one scan result, recorded before the farmer sees it (DFD 3.7),
    unrecognized results included. disease_id is set exactly when the result is 'diseased'."""

    __tablename__ = "diagnosis"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "(result_status = 'diseased') = (disease_id IS NOT NULL)",
            name="disease_with_diseased",
        ),
        Index("ix_diagnosis_user_id_created_at", "user_id", "created_at"),
    )

    diagnosis_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    crop_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("crop.crop_id"))
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("crop_cycle.cycle_id"))
    disease_id: Mapped[int | None] = mapped_column(ForeignKey("disease.disease_id"))
    # Key of the photo under LEAF_IMAGE_DIR, e.g. leaf/2026/10/1024.jpg; no image data here.
    image_path: Mapped[str] = mapped_column(String(255))
    predicted_label: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    result_status: Mapped[ResultStatus] = mapped_column(result_status)
    model_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
