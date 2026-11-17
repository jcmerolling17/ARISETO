from datetime import datetime

from pydantic import BaseModel

from app.models.enums import PathogenType, ResultStatus, TreatmentType


class TreatmentOut(BaseModel):
    step_no: int
    treatment_type: TreatmentType
    instruction_en: str
    instruction_fil: str | None
    source_reference: str


class DiseaseInfo(BaseModel):
    """The disease as it is now in the knowledge base, with its steps in order."""

    disease_id: int
    disease_name: str
    local_name: str | None
    pathogen_type: PathogenType
    symptoms: str | None
    description_en: str | None
    description_fil: str | None
    impact_en: str | None
    impact_fil: str | None
    treatments: list[TreatmentOut]


class DiagnosisOut(BaseModel):
    """POST /diagnoses and GET /diagnoses/{diagnosis_id}; disease is null unless diseased."""

    diagnosis_id: int
    result_status: ResultStatus
    confidence: float
    crop_name: str
    disease: DiseaseInfo | None
    model_version: str
    created_at: datetime


class DiagnosisItem(BaseModel):
    """One row of GET /diagnoses; field_name is null when no field was chosen."""

    diagnosis_id: int
    created_at: datetime
    crop_name: str
    field_name: str | None
    result_status: ResultStatus
    disease_name: str | None
    local_name: str | None
    confidence: float


class DiseaseSummary(BaseModel):
    """One row of GET /diseases."""

    disease_id: int
    crop_name: str
    disease_name: str
    local_name: str | None
    model_class_label: str
    pathogen_type: PathogenType
    treatment_count: int
