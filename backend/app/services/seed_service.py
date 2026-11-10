"""Load the reference data in app/seeds/: barangays (PSGC codes and center points), MPMPC's
crop varieties, and the crop calendar templates. Safe to run again: existing barangays are
updated by psgc_code, varieties by crop plus variety_name, and template tasks by variety,
anchor, day_offset and task_name; nothing is ever removed."""

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Boolean, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.constants import MUNICIPALITIES
from app.models import Barangay, CalendarTemplateTask, Crop, CropVariety
from app.models.enums import CalendarAnchor, GrowthStage, MaturityClass, TaskType

SEEDS_DIR = Path(__file__).resolve().parents[1] / "seeds"
BARANGAYS_CSV = SEEDS_DIR / "barangays.csv"
VARIETIES_CSV = SEEDS_DIR / "varieties.csv"
CALENDAR_CSV = SEEDS_DIR / "calendar_templates.csv"

BARANGAY_COLUMNS = [
    "psgc_code",
    "municipality",
    "barangay_name",
    "center_latitude",
    "center_longitude",
]
VARIETY_COLUMNS = ["crop", "variety_name", "maturity_class", "maturity_days", "source"]
CALENDAR_COLUMNS = [
    "crop",
    "anchor",
    "day_offset",
    "day_offset_end",
    "repeat_every_days",
    "repeat_until_anchor",
    "repeat_until_offset",
    "growth_stage",
    "task_type",
    "is_weather_sensitive",
    "task_name",
    "description",
    "source_reference",
]

# In an upsert's RETURNING, xmax is 0 for a newly inserted row and nonzero for an updated one.
_INSERTED = literal_column("(xmax = 0)", Boolean)


class SeedFileError(ValueError):
    """A seed file row that can't be loaded; the message names the file and line."""


@dataclass
class SeedResult:
    added: int = 0
    updated: int = 0


def _read_rows(path: Path, columns: list[str]) -> list[tuple[int, dict[str, str]]]:
    """(line number, row) pairs, after checking the header."""
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != columns:
            raise SeedFileError(f"{path.name}: expected columns {', '.join(columns)}")
        return [(reader.line_num, row) for row in reader]


def _upsert(db: Session, statement) -> SeedResult:
    """Run an INSERT ... ON CONFLICT DO UPDATE ... RETURNING _INSERTED and count the rows."""
    result = SeedResult()
    for inserted in db.scalars(statement):
        if inserted:
            result.added += 1
        else:
            result.updated += 1
    return result


def _barangay_values(path: Path) -> list[dict]:
    values = []
    for line, row in _read_rows(path, BARANGAY_COLUMNS):
        if row["municipality"] not in MUNICIPALITIES:
            raise SeedFileError(f"{path.name} line {line}: unknown municipality")
        try:
            latitude = Decimal(row["center_latitude"])
            longitude = Decimal(row["center_longitude"])
        except ArithmeticError as exc:
            raise SeedFileError(f"{path.name} line {line}: bad coordinates") from exc
        values.append(
            {
                "psgc_code": row["psgc_code"],
                "municipality": row["municipality"],
                "barangay_name": row["barangay_name"],
                "center_latitude": latitude,
                "center_longitude": longitude,
            }
        )
    return values


def _variety_values(db: Session, path: Path) -> list[dict]:
    crop_ids = {
        name.lower(): crop_id for crop_id, name in db.execute(select(Crop.crop_id, Crop.crop_name))
    }
    classes = {member.value for member in MaturityClass}
    values = []
    for line, row in _read_rows(path, VARIETY_COLUMNS):
        crop_id = crop_ids.get(row["crop"].lower())
        if crop_id is None:
            raise SeedFileError(f"{path.name} line {line}: unknown crop")
        if row["maturity_class"] not in classes:
            raise SeedFileError(f"{path.name} line {line}: unknown maturity_class")
        days = row["maturity_days"]
        if not days.isdigit() or int(days) <= 0:
            raise SeedFileError(f"{path.name} line {line}: maturity_days must be a whole number")
        values.append(
            {
                "crop_id": crop_id,
                "variety_name": row["variety_name"],
                "maturity_class": row["maturity_class"],
                "maturity_days": int(days),
            }
        )
    return values


def _whole_number(path: Path, line: int, name: str, raw: str) -> int | None:
    """An optional whole number (negative allowed); None when the cell is empty."""
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise SeedFileError(f"{path.name} line {line}: {name} must be a whole number") from exc


def _choice(path: Path, line: int, name: str, raw: str, allowed: set[str]) -> str:
    if raw not in allowed:
        raise SeedFileError(f"{path.name} line {line}: unknown {name}")
    return raw


def _template_rows(path: Path) -> list[tuple[str, dict]]:
    """(crop name, template values without variety_id) for each row of the calendar file."""
    anchors = {member.value for member in CalendarAnchor}
    stages = {member.value for member in GrowthStage}
    task_types = {member.value for member in TaskType}
    rows = []
    for line, row in _read_rows(path, CALENDAR_COLUMNS):
        repeat_anchor = row["repeat_until_anchor"]
        values = {
            "anchor": _choice(path, line, "anchor", row["anchor"], anchors),
            "day_offset": _whole_number(path, line, "day_offset", row["day_offset"]),
            "day_offset_end": _whole_number(path, line, "day_offset_end", row["day_offset_end"]),
            "repeat_every_days": _whole_number(
                path, line, "repeat_every_days", row["repeat_every_days"]
            ),
            "repeat_until_anchor": (
                _choice(path, line, "repeat_until_anchor", repeat_anchor, anchors)
                if repeat_anchor
                else None
            ),
            "repeat_until_offset": _whole_number(
                path, line, "repeat_until_offset", row["repeat_until_offset"]
            ),
            "growth_stage": _choice(path, line, "growth_stage", row["growth_stage"], stages),
            "task_type": _choice(path, line, "task_type", row["task_type"], task_types),
            "is_weather_sensitive": _choice(
                path, line, "is_weather_sensitive", row["is_weather_sensitive"], {"true", "false"}
            )
            == "true",
            "task_name": row["task_name"],
            "description": row["description"] or None,
            "source_reference": row["source_reference"],
        }
        if values["day_offset"] is None:
            raise SeedFileError(f"{path.name} line {line}: day_offset is required")
        if not values["task_name"] or not values["source_reference"]:
            raise SeedFileError(f"{path.name} line {line}: task_name and source are required")
        repeat = (
            values["repeat_every_days"],
            values["repeat_until_anchor"],
            values["repeat_until_offset"],
        )
        if len({value is None for value in repeat}) != 1:
            raise SeedFileError(f"{path.name} line {line}: repeat columns go together")
        rows.append((row["crop"].lower(), values))
    return rows


def seed_calendar_templates(db: Session, path: Path = CALENDAR_CSV) -> SeedResult:
    """Copy each crop's template tasks to every variety of that crop. Calendars already
    generated keep their tasks; a change here affects cycles created afterwards."""
    rows = _template_rows(path)
    varieties: dict[str, list[int]] = {}
    for variety_id, crop_name in db.execute(
        select(CropVariety.variety_id, Crop.crop_name).join(Crop)
    ):
        varieties.setdefault(crop_name.lower(), []).append(variety_id)
    values = [
        {"variety_id": variety_id, **template}
        for crop, template in rows
        for variety_id in varieties.get(crop, [])
    ]
    if not values:
        return SeedResult()
    key = ["variety_id", "anchor", "day_offset", "task_name"]
    statement = insert(CalendarTemplateTask).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=key,
        set_={name: statement.excluded[name] for name in values[0] if name not in key},
    ).returning(_INSERTED)
    return _upsert(db, statement)


def seed_barangays(db: Session, path: Path = BARANGAYS_CSV) -> SeedResult:
    values = _barangay_values(path)
    statement = insert(Barangay).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[Barangay.psgc_code],
        set_={
            "municipality": statement.excluded.municipality,
            "barangay_name": statement.excluded.barangay_name,
            "center_latitude": statement.excluded.center_latitude,
            "center_longitude": statement.excluded.center_longitude,
        },
    ).returning(_INSERTED)
    return _upsert(db, statement)


def seed_varieties(db: Session, path: Path = VARIETIES_CSV) -> SeedResult:
    values = _variety_values(db, path)
    statement = insert(CropVariety).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[CropVariety.crop_id, CropVariety.variety_name],
        set_={
            "maturity_class": statement.excluded.maturity_class,
            "maturity_days": statement.excluded.maturity_days,
        },
    ).returning(_INSERTED)
    return _upsert(db, statement)


def seed_all(db: Session) -> dict[str, SeedResult]:
    """Load the three files in one transaction; a bad row in any leaves nothing changed.
    Varieties go first, so the calendar templates reach every variety."""
    results = {
        "barangays": seed_barangays(db),
        "varieties": seed_varieties(db),
        "calendar templates": seed_calendar_templates(db),
    }
    db.commit()
    return results


def barangay_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(Barangay.municipality, func.count())
        .group_by(Barangay.municipality)
        .order_by(Barangay.municipality)
    )
    return dict(rows.all())


def variety_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(Crop.crop_name, func.count(CropVariety.variety_id))
        .join(CropVariety, CropVariety.crop_id == Crop.crop_id, isouter=True)
        .group_by(Crop.crop_name)
        .order_by(Crop.crop_name)
    )
    return dict(rows.all())


def template_counts(db: Session) -> dict[str, int]:
    """Calendar template tasks per crop."""
    rows = db.execute(
        select(Crop.crop_name, func.count(CalendarTemplateTask.template_task_id))
        .join(CropVariety, CropVariety.crop_id == Crop.crop_id, isouter=True)
        .join(
            CalendarTemplateTask,
            CalendarTemplateTask.variety_id == CropVariety.variety_id,
            isouter=True,
        )
        .group_by(Crop.crop_name)
        .order_by(Crop.crop_name)
    )
    return dict(rows.all())
