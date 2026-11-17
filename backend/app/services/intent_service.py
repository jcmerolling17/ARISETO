"""The chatbot's intents (DFD 6.5; Section 6, import-intents and check-chatbot).

intents.csv is loaded in one transaction: intents are added or updated by intent_tag, and
rows already in the database but not in the file stay as they are. Every row is checked
first; any bad row rejects the whole file and nothing is saved.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatIntent, Crop
from app.services.chat_model import TAG_MAX_LENGTH, valid_tag
from app.services.chat_service import FARM_DATA_TAGS

INTENT_COLUMNS = ["intent_tag", "crop_name", "response_en", "response_fil", "source_reference"]
SOURCE_MAX_LENGTH = 255
MAX_ERRORS_SHOWN = 20


class ImportFileError(ValueError):
    """Rows that can't be loaded; each message names the line."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass
class ImportResult:
    added: int = 0
    updated: int = 0


@dataclass
class _Errors:
    messages: list[str] = field(default_factory=list)

    def add(self, line: int, message: str) -> None:
        self.messages.append(f"intents.csv line {line}: {message}")


def read_csv(path: Path, columns: list[str]) -> list[tuple[int, dict[str, str]]]:
    """(line number, row) pairs with values trimmed; UTF-8 with or without a BOM (Excel).
    Raises ImportFileError for a missing file, wrong header, or short rows."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != columns:
                raise ImportFileError([f"{path.name}: expected columns {','.join(columns)}"])
            rows, errors = [], []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    errors.append(f"{path.name} line {reader.line_num}: wrong number of values")
                    continue
                rows.append((reader.line_num, {k: v.strip() for k, v in row.items()}))
    except FileNotFoundError as exc:
        raise ImportFileError([f"{path.name}: file not found"]) from exc
    except UnicodeDecodeError as exc:
        raise ImportFileError([f"{path.name}: not UTF-8 text"]) from exc
    if errors:
        raise ImportFileError(errors[:MAX_ERRORS_SHOWN])
    return rows


def _parse(rows, crops: dict[str, Crop]) -> dict[str, dict]:
    errors = _Errors()
    intents: dict[str, dict] = {}
    for line, row in rows:
        tag = row["intent_tag"]
        if not valid_tag(tag):
            errors.add(
                line,
                f"intent_tag {tag!r} must be a-z, 0-9 and _ (at most {TAG_MAX_LENGTH} characters)",
            )
        elif tag in intents:
            errors.add(line, f"intent_tag {tag!r} is listed twice")
        crop = crops.get(row["crop_name"].lower()) if row["crop_name"] else None
        if row["crop_name"] and crop is None:
            errors.add(line, f"unknown crop_name {row['crop_name']!r}")
        if not row["response_en"]:
            errors.add(line, "response_en is required")
        if not row["source_reference"] and tag not in FARM_DATA_TAGS:
            errors.add(line, "source_reference is required")
        if len(row["source_reference"]) > SOURCE_MAX_LENGTH:
            errors.add(line, f"source_reference is longer than {SOURCE_MAX_LENGTH} characters")
        intents[tag] = {
            "crop_id": crop.crop_id if crop else None,
            "response_en": row["response_en"],
            "response_fil": row["response_fil"] or None,
            "source_reference": row["source_reference"] or None,
        }
    if not errors.messages and not intents:
        errors.messages.append("intents.csv: no intents listed")
    if errors.messages:
        raise ImportFileError(errors.messages[:MAX_ERRORS_SHOWN])
    return intents


def import_intents(db: Session, path: Path, *, dry_run: bool = False) -> ImportResult:
    """Load intents.csv in one transaction, or nothing. New intents are active; an updated
    intent keeps its is_active. With dry_run, check and count only."""
    rows = read_csv(path, INTENT_COLUMNS)
    crops = {crop.crop_name.lower(): crop for crop in db.scalars(select(Crop))}
    intents = _parse(rows, crops)

    result = ImportResult()
    try:
        existing = {
            intent.intent_tag: intent
            for intent in db.scalars(select(ChatIntent).where(ChatIntent.intent_tag.in_(intents)))
        }
        for tag, values in intents.items():
            intent = existing.get(tag)
            if intent is None:
                db.add(ChatIntent(intent_tag=tag, is_active=True, **values))
                result.added += 1
            else:
                for name, value in values.items():
                    setattr(intent, name, value)
                result.updated += 1
        db.flush()
        if dry_run:
            db.rollback()
        else:
            db.commit()
    except BaseException:
        db.rollback()
        raise
    return result


def active_tags(db: Session) -> set[str]:
    """Every active intent_tag (check-chatbot)."""
    return set(db.scalars(select(ChatIntent.intent_tag).where(ChatIntent.is_active.is_(True))))
