"""import-diseases (Section 6, "Disease detection runtime (Phase 10)"): both CSV files in one
transaction, diseases added or updated by model_class_label, steps replaced, and any bad row
rejects everything. The rows are made-up test data, not knowledge-base content."""

import csv

import pytest
from sqlalchemy import func, select

from app import cli
from app.models import Disease, Treatment
from app.services.disease_service import DISEASE_COLUMNS, TREATMENT_COLUMNS


def _disease(**overrides) -> dict:
    row = {
        "crop_name": "corn",
        "disease_name": "Test condition A",
        "local_name": "",
        "model_class_label": "corn_test_a",
        "pathogen_type": "fungal",
        "symptoms": "Sign one\n\n  Sign two  ",
        "description_en": "Test description",
        "description_fil": "",
        "impact_en": "Test impact",
        "impact_fil": "",
    }
    row.update(overrides)
    return row


def _step(label="corn_test_a", step_no="1", **overrides) -> dict:
    row = {
        "model_class_label": label,
        "step_no": step_no,
        "treatment_type": "cultural",
        "instruction_en": f"Step {step_no}",
        "instruction_fil": "",
        "source_reference": "Test guide",
    }
    row.update(overrides)
    return row


def _write(path, columns, rows) -> str:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def _files(tmp_path, diseases, steps) -> list[str]:
    return [
        _write(tmp_path / "diseases.csv", DISEASE_COLUMNS, diseases),
        _write(tmp_path / "treatments.csv", TREATMENT_COLUMNS, steps),
    ]


def _counts(db) -> tuple[int, int]:
    db.expire_all()
    return (
        db.scalar(select(func.count()).select_from(Disease)),
        db.scalar(select(func.count()).select_from(Treatment)),
    )


def test_import_adds_then_updates_and_replaces_steps(tmp_path, db, capsys) -> None:
    files = _files(
        tmp_path,
        [_disease(), _disease(crop_name="Rice", model_class_label="rice_test_b")],
        [_step(step_no="2"), _step(step_no="1"), _step("rice_test_b")],
    )

    assert cli.main(["import-diseases", *files]) == 0
    assert "Imported 2 diseases (2 added, 0 updated) with 3 treatment steps." in (
        capsys.readouterr().out
    )
    corn = db.scalar(select(Disease).where(Disease.model_class_label == "corn_test_a"))
    assert corn.symptoms == "Sign one\nSign two"
    assert corn.local_name is None
    assert corn.description_fil is None

    files = _files(
        tmp_path,
        [_disease(disease_name="Renamed", local_name="Lokal")],
        [_step(step_no="1", instruction_en="Only step")],
    )
    assert cli.main(["import-diseases", *files]) == 0
    assert "(0 added, 1 updated) with 1 treatment steps" in capsys.readouterr().out

    db.expire_all()
    corn = db.scalar(select(Disease).where(Disease.model_class_label == "corn_test_a"))
    assert (corn.disease_name, corn.local_name) == ("Renamed", "Lokal")
    steps = db.scalars(select(Treatment).where(Treatment.disease_id == corn.disease_id)).all()
    assert [(s.step_no, s.instruction_en) for s in steps] == [(1, "Only step")]
    assert _counts(db) == (2, 2)  # the rice disease and its step are untouched


def test_dry_run_saves_nothing(tmp_path, db, capsys) -> None:
    files = _files(tmp_path, [_disease()], [_step()])

    assert cli.main(["import-diseases", *files, "--dry-run"]) == 0

    assert "Dry run, nothing saved: would import 1 diseases (1 added, 0 updated)" in (
        capsys.readouterr().out
    )
    assert _counts(db) == (0, 0)


def test_bom_from_excel_is_accepted(tmp_path, db) -> None:
    diseases, steps = _files(tmp_path, [_disease()], [_step()])
    path = tmp_path / "diseases.csv"
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())

    assert cli.main(["import-diseases", diseases, steps]) == 0
    assert _counts(db) == (1, 1)


@pytest.mark.parametrize(
    ("diseases", "steps", "message"),
    [
        ([_disease(crop_name="wheat")], [_step()], "unknown crop_name 'wheat'"),
        ([_disease(pathogen_type="mold")], [_step()], "unknown pathogen_type 'mold'"),
        ([_disease(disease_name="")], [_step()], "disease_name is required"),
        ([_disease(model_class_label="Corn A")], [_step("Corn A")], "is not <crop>_<condition>"),
        ([_disease(model_class_label="rice_test_a")], [_step("rice_test_a")], "not a corn label"),
        ([_disease(model_class_label="corn_healthy")], [_step("corn_healthy")], "healthy class"),
        ([_disease(), _disease()], [_step()], "listed twice"),
        ([_disease()], [_step(source_reference="")], "source_reference is required"),
        ([_disease()], [_step(treatment_type="spray")], "unknown treatment_type 'spray'"),
        ([_disease()], [_step(step_no="0")], "step_no must be a whole number above 0"),
        ([_disease()], [_step(), _step()], "step 1 of 'corn_test_a' is listed twice"),
        ([_disease()], [_step(instruction_en="")], "instruction_en is required"),
        ([_disease()], [_step(), _step("corn_other")], "'corn_other' is not in diseases.csv"),
        ([_disease()], [], "'corn_test_a' has no treatment steps"),
        ([_disease(disease_name="x" * 101)], [_step()], "longer than 100 characters"),
    ],
)
def test_a_bad_row_rejects_both_files(tmp_path, db, capsys, diseases, steps, message) -> None:
    files = _files(tmp_path, diseases + [_disease(model_class_label="corn_fine")], steps)
    # corn_fine is valid but needs its own step; the bad row must still stop everything.
    with (tmp_path / "treatments.csv").open("a", newline="", encoding="utf-8") as file:
        csv.DictWriter(file, fieldnames=TREATMENT_COLUMNS).writerow(_step("corn_fine"))

    assert cli.main(["import-diseases", *files]) == 1

    err = capsys.readouterr().err
    assert "Nothing imported:" in err
    assert message in err
    assert _counts(db) == (0, 0)


def test_wrong_header_is_rejected(tmp_path, db, capsys) -> None:
    diseases = _write(tmp_path / "diseases.csv", ["crop", "name"], [{"crop": "corn", "name": "x"}])
    steps = _write(tmp_path / "treatments.csv", TREATMENT_COLUMNS, [_step()])

    assert cli.main(["import-diseases", diseases, steps]) == 1

    assert "diseases.csv: expected columns crop_name,disease_name" in capsys.readouterr().err
    assert _counts(db) == (0, 0)


def test_missing_file(tmp_path, capsys) -> None:
    assert cli.main(["import-diseases", str(tmp_path / "a.csv"), str(tmp_path / "b.csv")]) == 1

    assert "file not found" in capsys.readouterr().err
