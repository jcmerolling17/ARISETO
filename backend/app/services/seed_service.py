"""Load the reference data in app/seeds/: barangays (PSGC codes and center points) and
MPMPC's crop varieties. Safe to run again: existing barangays are updated by psgc_code and
existing varieties by crop plus variety_name."""

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Boolean, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.constants import MUNICIPALITIES
from app.models import Barangay, Crop, CropVariety
from app.models.enums import MaturityClass

SEEDS_DIR = Path(__file__).resolve().parents[1] / "seeds"
BARANGAYS_CSV = SEEDS_DIR / "barangays.csv"
VARIETIES_CSV = SEEDS_DIR / "varieties.csv"

BARANGAY_COLUMNS = [
    "psgc_code",
    "municipality",
    "barangay_name",
    "center_latitude",
    "center_longitude",
]
VARIETY_COLUMNS = ["crop", "variety_name", "maturity_class", "maturity_days", "source"]

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
    """Load both files in one transaction; a bad row in either leaves nothing changed."""
    results = {"barangays": seed_barangays(db), "varieties": seed_varieties(db)}
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
