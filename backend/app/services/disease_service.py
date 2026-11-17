"""The disease and treatment knowledge base (DFD 3.6 and 3.9; Section 6, GET /diseases and
import-diseases).

The team's two CSV files are loaded in one transaction: diseases are added or updated by
model_class_label, and each listed disease's treatment steps are replaced. Every row is
checked first; any bad row rejects both files and nothing is saved.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Crop, Disease, Treatment
from app.models.enums import PathogenType, TreatmentType
from app.schemas.diagnosis import DiseaseSummary
from app.services.disease_model import LABEL_PATTERN

DISEASE_COLUMNS = [
    "crop_name",
    "disease_name",
    "local_name",
    "model_class_label",
    "pathogen_type",
    "symptoms",
    "description_en",
    "description_fil",
    "impact_en",
    "impact_fil",
]
TREATMENT_COLUMNS = [
    "model_class_label",
    "step_no",
    "treatment_type",
    "instruction_en",
    "instruction_fil",
    "source_reference",
]
MAX_ERRORS_SHOWN = 20
SMALLINT_MAX = 32767


def list_diseases(db: Session, crop_id: int | None) -> list[DiseaseSummary]:
    """Diseases with their number of treatment steps, by crop and name.
    Errors: 422 crop_not_found."""
    if crop_id is not None and db.get(Crop, crop_id) is None:
        raise AppError(422, "crop_not_found")
    steps = (
        select(Treatment.disease_id, func.count().label("count"))
        .group_by(Treatment.disease_id)
        .subquery()
    )
    query = (
        select(Disease, Crop.crop_name, func.coalesce(steps.c.count, 0))
        .join(Crop, Crop.crop_id == Disease.crop_id)
        .outerjoin(steps, steps.c.disease_id == Disease.disease_id)
        .order_by(Disease.crop_id, Disease.disease_name, Disease.disease_id)
    )
    if crop_id is not None:
        query = query.where(Disease.crop_id == crop_id)
    return [
        DiseaseSummary(
            disease_id=disease.disease_id,
            crop_name=crop_name,
            disease_name=disease.disease_name,
            local_name=disease.local_name,
            model_class_label=disease.model_class_label,
            pathogen_type=disease.pathogen_type,
            treatment_count=count,
        )
        for disease, crop_name, count in db.execute(query)
    ]


# ---------- import-diseases ----------


class ImportFileError(ValueError):
    """Rows that can't be loaded; each message names the file and line."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass
class ImportResult:
    added: int = 0
    updated: int = 0
    steps: int = 0


@dataclass
class _Errors:
    messages: list[str] = field(default_factory=list)

    def add(self, file: str, line: int, message: str) -> None:
        self.messages.append(f"{file} line {line}: {message}")


def _read(path: Path, columns: list[str], errors: _Errors) -> list[tuple[int, dict[str, str]]]:
    """(line number, row) pairs with values trimmed; utf-8 with or without a BOM (Excel)."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != columns:
                errors.messages.append(f"{path.name}: expected columns {','.join(columns)}")
                return []
            rows = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    errors.add(path.name, reader.line_num, "wrong number of values")
                    continue
                rows.append((reader.line_num, {k: v.strip() for k, v in row.items()}))
            return rows
    except FileNotFoundError:
        errors.messages.append(f"{path.name}: file not found")
    except UnicodeDecodeError:
        errors.messages.append(f"{path.name}: not UTF-8 text")
    return []


def _optional(value: str) -> str | None:
    return value or None


def _lines(value: str) -> str | None:
    """Symptoms: one per line, blank lines dropped."""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return "\n".join(lines) or None


def _check_length(errors: _Errors, file: str, line: int, row: dict, name: str, limit: int):
    if len(row[name]) > limit:
        errors.add(file, line, f"{name} is longer than {limit} characters")


def _parse_diseases(rows, crops: dict[str, Crop], errors: _Errors) -> dict[str, dict]:
    """model_class_label -> the disease's column values."""
    file = "diseases.csv"
    diseases: dict[str, dict] = {}
    pathogen_types = {member.value for member in PathogenType}
    for line, row in rows:
        crop = crops.get(row["crop_name"].lower())
        label = row["model_class_label"]
        if crop is None:
            errors.add(file, line, f"unknown crop_name {row['crop_name']!r}")
        for required in ("disease_name", "model_class_label", "pathogen_type"):
            if not row[required]:
                errors.add(file, line, f"{required} is required")
        _check_length(errors, file, line, row, "disease_name", 100)
        _check_length(errors, file, line, row, "local_name", 100)
        _check_length(errors, file, line, row, "model_class_label", 80)
        if row["pathogen_type"] and row["pathogen_type"] not in pathogen_types:
            errors.add(file, line, f"unknown pathogen_type {row['pathogen_type']!r}")
        if label:
            crop_key = crop.crop_name.lower() if crop else None
            if not LABEL_PATTERN.fullmatch(label):
                errors.add(file, line, f"model_class_label {label!r} is not <crop>_<condition>")
            elif crop_key and not label.startswith(f"{crop_key}_"):
                errors.add(file, line, f"model_class_label {label!r} is not a {crop_key} label")
            elif label == f"{crop_key}_healthy":
                errors.add(file, line, f"{label!r} is the healthy class, not a disease")
            if label in diseases:
                errors.add(file, line, f"model_class_label {label!r} is listed twice")
        diseases[label] = {
            "crop_id": crop.crop_id if crop else None,
            "disease_name": row["disease_name"],
            "local_name": _optional(row["local_name"]),
            "pathogen_type": row["pathogen_type"],
            "symptoms": _lines(row["symptoms"]),
            "description_en": _optional(row["description_en"]),
            "description_fil": _optional(row["description_fil"]),
            "impact_en": _optional(row["impact_en"]),
            "impact_fil": _optional(row["impact_fil"]),
        }
    return diseases


def _parse_treatments(rows, labels: set[str], errors: _Errors) -> dict[str, list[dict]]:
    """model_class_label -> its steps."""
    file = "treatments.csv"
    steps: dict[str, list[dict]] = {}
    seen: set[tuple[str, int]] = set()
    treatment_types = {member.value for member in TreatmentType}
    for line, row in rows:
        label = row["model_class_label"]
        if label not in labels:
            errors.add(file, line, f"model_class_label {label!r} is not in diseases.csv")
        try:
            step_no = int(row["step_no"])
        except ValueError:
            step_no = 0
        if not 0 < step_no <= SMALLINT_MAX:
            errors.add(file, line, "step_no must be a whole number above 0")
        elif (label, step_no) in seen:
            errors.add(file, line, f"step {step_no} of {label!r} is listed twice")
        seen.add((label, step_no))
        if row["treatment_type"] not in treatment_types:
            errors.add(file, line, f"unknown treatment_type {row['treatment_type']!r}")
        for required in ("instruction_en", "source_reference"):
            if not row[required]:
                errors.add(file, line, f"{required} is required")
        _check_length(errors, file, line, row, "source_reference", 255)
        steps.setdefault(label, []).append(
            {
                "step_no": step_no,
                "treatment_type": row["treatment_type"],
                "instruction_en": row["instruction_en"],
                "instruction_fil": _optional(row["instruction_fil"]),
                "source_reference": row["source_reference"],
            }
        )
    return steps


def import_files(
    db: Session, diseases_csv: Path, treatments_csv: Path, *, dry_run: bool = False
) -> ImportResult:
    """Load both files in one transaction, or nothing. With dry_run, check and count only.
    Raises ImportFileError listing the bad rows."""
    errors = _Errors()
    disease_rows = _read(diseases_csv, DISEASE_COLUMNS, errors)
    treatment_rows = _read(treatments_csv, TREATMENT_COLUMNS, errors)
    crops = {crop.crop_name.lower(): crop for crop in db.scalars(select(Crop))}
    diseases = _parse_diseases(disease_rows, crops, errors)
    steps = _parse_treatments(treatment_rows, set(diseases), errors)
    if not errors.messages and not diseases:
        errors.messages.append("diseases.csv: no diseases listed")
    for label in diseases:
        if label and label not in steps:
            errors.messages.append(f"diseases.csv: {label!r} has no treatment steps")
    if errors.messages:
        raise ImportFileError(errors.messages[:MAX_ERRORS_SHOWN])

    result = ImportResult()
    try:
        existing = {
            disease.model_class_label: disease
            for disease in db.scalars(
                select(Disease).where(Disease.model_class_label.in_(diseases))
            )
        }
        for label, values in diseases.items():
            disease = existing.get(label)
            if disease is None:
                db.add(Disease(model_class_label=label, **values))
                result.added += 1
            else:
                for name, value in values.items():
                    setattr(disease, name, value)
                result.updated += 1
        db.flush()
        ids = dict(
            db.execute(
                select(Disease.model_class_label, Disease.disease_id).where(
                    Disease.model_class_label.in_(diseases)
                )
            ).all()
        )
        db.execute(delete(Treatment).where(Treatment.disease_id.in_(ids.values())))
        for label, label_steps in steps.items():
            for step in label_steps:
                db.add(Treatment(disease_id=ids[label], **step))
                result.steps += 1
        db.flush()
        if dry_run:
            db.rollback()
        else:
            db.commit()
    except BaseException:
        db.rollback()
        raise
    return result


def known_labels(db: Session) -> set[str]:
    """Every model_class_label in the knowledge base (check-model)."""
    return set(db.scalars(select(Disease.model_class_label)))
