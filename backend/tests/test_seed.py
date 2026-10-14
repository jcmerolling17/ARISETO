from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app import cli
from app.models import Barangay, Crop, CropVariety
from app.services import seed_service
from app.services.seed_service import SeedFileError

BARANGAYS_PER_MUNICIPALITY = {
    "Abra de Ilog": 10,
    "Calintaan": 7,
    "Looc": 9,
    "Lubang": 16,
    "Magsaysay": 12,
    "Mamburao": 15,
    "Paluan": 12,
    "Rizal": 11,
    "Sablayan": 22,
    "San Jose": 39,
    "Santa Cruz": 11,
}
VARIETIES_PER_CROP = {"Corn": 5, "Onion": 5, "Rice": 5}


def test_loads_every_barangay_and_variety(db) -> None:
    results = seed_service.seed_all(db)

    assert (results["barangays"].added, results["barangays"].updated) == (164, 0)
    assert (results["varieties"].added, results["varieties"].updated) == (15, 0)
    assert seed_service.barangay_counts(db) == BARANGAYS_PER_MUNICIPALITY
    assert seed_service.variety_counts(db) == VARIETIES_PER_CROP

    tangkalan = db.scalar(select(Barangay).where(Barangay.psgc_code == "1705106006"))
    assert (tangkalan.municipality, tangkalan.barangay_name) == ("Mamburao", "Tangkalan")
    assert (tangkalan.center_latitude, tangkalan.center_longitude) == (
        Decimal("13.271995"),
        Decimal("120.624727"),
    )
    c4_green = db.scalar(select(CropVariety).where(CropVariety.variety_name == "C4-GREEN"))
    assert (db.get(Crop, c4_green.crop_id).crop_name, c4_green.maturity_class) == (
        "Rice",
        "very_early",
    )
    assert c4_green.maturity_days == 100


def test_running_again_updates_instead_of_duplicating(db) -> None:
    seed_service.seed_all(db)
    tangkalan = db.scalar(select(Barangay).where(Barangay.psgc_code == "1705106006"))
    tangkalan.center_latitude = Decimal("1")
    nk6410 = db.scalar(select(CropVariety).where(CropVariety.variety_name == "NK6410"))
    nk6410.maturity_days = 1
    db.commit()
    ids_before = db.scalars(select(Barangay.barangay_id).order_by(Barangay.barangay_id)).all()

    results = seed_service.seed_all(db)

    assert (results["barangays"].added, results["barangays"].updated) == (0, 164)
    assert (results["varieties"].added, results["varieties"].updated) == (0, 15)
    db.expire_all()
    assert tangkalan.center_latitude == Decimal("13.271995")
    assert nk6410.maturity_days == 90
    assert db.scalars(select(Barangay.barangay_id).order_by(Barangay.barangay_id)).all() == (
        ids_before
    )


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


BARANGAY_HEADER = "psgc_code,municipality,barangay_name,center_latitude,center_longitude\n"
VARIETY_HEADER = "crop,variety_name,maturity_class,maturity_days,source\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("code,municipality\n1,Mamburao\n", "expected columns"),
        (BARANGAY_HEADER + "1,Manila,Tondo,14.6,120.9\n", "line 2: unknown municipality"),
        (BARANGAY_HEADER + "1,Mamburao,Tangkalan,north,120.6\n", "line 2: bad coordinates"),
    ],
)
def test_rejects_bad_barangay_rows(db, tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(SeedFileError, match=message):
        seed_service.seed_barangays(db, _write(tmp_path / "barangays.csv", text))


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("wheat,X,early,90,MPMPC", "unknown crop"),
        ("corn,X,fast,90,MPMPC", "unknown maturity_class"),
        ("corn,X,early,0,MPMPC", "maturity_days must be a whole number"),
        ("corn,X,early,90.5,MPMPC", "maturity_days must be a whole number"),
    ],
)
def test_rejects_bad_variety_rows(db, tmp_path: Path, row: str, message: str) -> None:
    with pytest.raises(SeedFileError, match=f"line 2: {message}"):
        seed_service.seed_varieties(db, _write(tmp_path / "varieties.csv", VARIETY_HEADER + row))


def test_cli_seed_prints_the_counts(db, capsys) -> None:
    assert cli.main(["seed"]) == 0

    out = capsys.readouterr().out
    assert "barangays: 164 added, 0 updated" in out
    assert "varieties: 15 added, 0 updated" in out
    assert "Barangays per municipality (164 in total):" in out
    assert "  San Jose: 39" in out
    assert "Varieties per crop (15 in total):" in out
    assert "  Onion: 5" in out


def test_cli_seed_reports_a_bad_file(monkeypatch, db, tmp_path: Path, capsys) -> None:
    bad = _write(tmp_path / "varieties.csv", VARIETY_HEADER + "wheat,X,early,90,MPMPC\n")
    monkeypatch.setattr(seed_service.seed_varieties, "__defaults__", (bad,))

    assert cli.main(["seed"]) == 1

    assert "Nothing loaded: varieties.csv line 2: unknown crop" in capsys.readouterr().err
    # The barangays loaded before the bad file are rolled back too.
    assert db.scalar(select(Barangay)) is None
