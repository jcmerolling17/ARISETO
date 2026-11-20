"""POST and GET /diagnoses (Section 6; DFD 3.1-3.8) with a fake predictor: the result rules,
the photo checks, saving the photo with its row, and the owner-only reads.

Disease rows here are made-up test data (labels corn_test_*), not knowledge-base content."""

import io
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.diagnoses import get_predictor
from app.core.config import get_settings
from app.main import app
from app.models import Crop, Diagnosis, Disease, Treatment
from app.services.disease_model import Prediction
from tests.conftest import FarmSetup, auth_header

URL = "/api/v1/diagnoses"
THRESHOLD = 0.7


@dataclass
class FakePredictor:
    """Returns the prediction a test sets; records the photo sizes it was given."""

    label: str = "corn_healthy"
    confidence: float = 0.95
    version: str = "test-1.0"
    threshold: float = THRESHOLD
    seen: list[tuple[int, int]] = field(default_factory=list)

    def predict(self, image: Image.Image) -> Prediction:
        self.seen.append(image.size)
        return Prediction(self.label, self.confidence)


@pytest.fixture
def predictor() -> FakePredictor:
    fake = FakePredictor()
    app.dependency_overrides[get_predictor] = lambda: fake
    return fake


def photo(size=(300, 400), fmt="JPEG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (40, 120, 40)).save(buffer, format=fmt)
    return buffer.getvalue()


def scan(client, token, data=None, *, image=None, filename="leaf.jpg", mime="image/jpeg"):
    files = {"image": (filename, photo() if image is None else image, mime)}
    return client.post(URL, files=files, data=data or {}, headers=auth_header(token))


def crop_id(db: Session, name: str) -> int:
    return db.scalar(select(Crop.crop_id).where(Crop.crop_name == name))


def add_disease(db: Session, crop: str, label: str, steps=(2, 1, 3)) -> Disease:
    disease = Disease(
        crop_id=crop_id(db, crop),
        disease_name=f"Test condition {label}",
        local_name="Test local name",
        model_class_label=label,
        pathogen_type="fungal",
        symptoms="Sign one\nSign two",
        description_en="Test description",
        description_fil="Pagsubok na paglalarawan",
        impact_en="Test impact",
        impact_fil=None,
    )
    db.add(disease)
    db.flush()
    for step in steps:
        db.add(
            Treatment(
                disease_id=disease.disease_id,
                step_no=step,
                treatment_type="cultural",
                instruction_en=f"Step {step}",
                instruction_fil=None,
                source_reference=f"Test guide p. {step}",
            )
        )
    db.commit()
    return disease


def leaf_files() -> list[Path]:
    root = get_settings().leaf_image_dir
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


def diagnosis_count(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Diagnosis))


# ---------- No model ----------


def test_no_model_is_503_and_saves_nothing(client, member_token, farm: FarmSetup, db) -> None:
    response = scan(client, member_token, {"cycle_id": farm.cycle_ids["Field A"]})

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "model_unavailable"}}
    assert diagnosis_count(db) == 0
    assert leaf_files() == []


def test_api_starts_without_a_model_and_logs_one_warning(caplog) -> None:
    with caplog.at_level("WARNING", logger="app.disease"), TestClient(app):
        pass
    warnings = [r for r in caplog.records if r.name == "app.disease"]
    assert len(warnings) == 1
    assert "Disease detection is off: not configured" in warnings[0].getMessage()


# ---------- Result rules ----------


def test_diseased_returns_the_disease_with_steps_in_order(
    client, member_token, farm: FarmSetup, db, predictor
) -> None:
    disease = add_disease(db, "Corn", "corn_test_blight")
    predictor.label, predictor.confidence = "corn_test_blight", 0.91234

    response = scan(client, member_token, {"cycle_id": farm.cycle_ids["Field A"]})

    assert response.status_code == 201
    body = response.json()
    assert body["result_status"] == "diseased"
    assert body["confidence"] == 0.9123
    assert body["crop_name"] == "Corn"
    assert body["model_version"] == "test-1.0"
    assert body["disease"]["disease_id"] == disease.disease_id
    assert body["disease"]["local_name"] == "Test local name"
    assert body["disease"]["symptoms"] == "Sign one\nSign two"
    assert [s["step_no"] for s in body["disease"]["treatments"]] == [1, 2, 3]
    assert body["disease"]["treatments"][0]["source_reference"] == "Test guide p. 1"

    db.expire_all()
    saved = db.get(Diagnosis, body["diagnosis_id"])
    assert saved.disease_id == disease.disease_id
    assert saved.cycle_id == farm.cycle_ids["Field A"]
    assert saved.predicted_label == "corn_test_blight"
    assert saved.image_path.startswith("leaf/") and saved.image_path.endswith(
        f"/{saved.diagnosis_id}.jpg"
    )
    assert (get_settings().leaf_image_dir / saved.image_path).read_bytes() == photo()
    assert predictor.seen == [(300, 400)]


def test_healthy_label_above_the_threshold_is_healthy(
    client, member_token, farm: FarmSetup, predictor
) -> None:
    response = scan(client, member_token, {"cycle_id": farm.cycle_ids["Field A"]})

    assert response.status_code == 201
    assert response.json()["result_status"] == "healthy"
    assert response.json()["disease"] is None


@pytest.mark.parametrize(
    ("label", "confidence", "expected"),
    [
        ("corn_test_blight", 0.6999, "unrecognized"),  # below the threshold
        ("corn_healthy", 0.5, "unrecognized"),  # the threshold is checked first
        ("corn_test_blight", THRESHOLD, "diseased"),  # equal passes
        ("rice_test_blight", 0.99, "unrecognized"),  # another crop's label
        ("corn_no_row", 0.99, "unrecognized"),  # a label with no DISEASE row
        ("rice_healthy", 0.99, "unrecognized"),  # another crop's healthy class
    ],
)
def test_result_rules(
    client, member_token, farm: FarmSetup, db, predictor, label, confidence, expected
) -> None:
    add_disease(db, "Corn", "corn_test_blight")
    add_disease(db, "Rice", "rice_test_blight")
    predictor.label, predictor.confidence = label, confidence

    response = scan(client, member_token, {"cycle_id": farm.cycle_ids["Field A"]})

    assert response.status_code == 201
    body = response.json()
    assert body["result_status"] == expected
    assert (body["disease"] is not None) == (expected == "diseased")
    db.expire_all()
    saved = db.get(Diagnosis, body["diagnosis_id"])
    assert saved.predicted_label == label  # the raw label is kept, unrecognized included
    assert (saved.disease_id is not None) == (expected == "diseased")


def test_crop_id_without_a_field(client, member_token, db, predictor) -> None:
    predictor.label = "onion_healthy"

    response = scan(client, member_token, {"crop_id": crop_id(db, "Onion")})

    assert response.status_code == 201
    assert response.json()["crop_name"] == "Onion"
    assert response.json()["result_status"] == "healthy"
    listed = client.get(URL, headers=auth_header(member_token)).json()
    assert listed[0]["field_name"] is None
    assert listed[0]["crop_name"] == "Onion"


def test_cycle_and_matching_crop_id_are_accepted(
    client, member_token, farm: FarmSetup, db, predictor
) -> None:
    data = {"cycle_id": farm.cycle_ids["Field B"], "crop_id": crop_id(db, "Rice")}
    predictor.label = "rice_healthy"

    response = scan(client, member_token, data)

    assert response.status_code == 201
    assert response.json()["crop_name"] == "Rice"


def test_a_worker_on_the_farm_can_scan(client, worker_token, farm: FarmSetup, predictor) -> None:
    response = scan(client, worker_token, {"cycle_id": farm.cycle_ids["Field A"]})

    assert response.status_code == 201


# ---------- Crop errors ----------


def test_crop_required(client, member_token, predictor) -> None:
    response = scan(client, member_token, {})

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "crop_required"}}


def test_crop_not_found(client, member_token, predictor) -> None:
    response = scan(client, member_token, {"crop_id": 999})

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "crop_not_found"}}


def test_crop_mismatch(client, member_token, farm: FarmSetup, db, predictor) -> None:
    data = {"cycle_id": farm.cycle_ids["Field A"], "crop_id": crop_id(db, "Rice")}

    response = scan(client, member_token, data)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "crop_mismatch"}}


def test_cycle_not_found_for_a_missing_cycle_or_a_non_member(
    client, member_token, outsider_token, farm: FarmSetup, predictor, db
) -> None:
    for token, cycle in ((member_token, 99999), (outsider_token, farm.cycle_ids["Field A"])):
        response = scan(client, token, {"cycle_id": cycle})
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "cycle_not_found"}}
    assert diagnosis_count(db) == 0


# ---------- Image errors ----------


@pytest.mark.parametrize(
    ("image", "status", "code"),
    [
        (b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024), 413, "image_too_large"),
        (photo(fmt="GIF"), 415, "unsupported_image_type"),
        (b"not an image at all", 415, "unsupported_image_type"),
        (photo()[:200], 422, "image_unreadable"),
        (photo(size=(223, 600)), 422, "image_too_small"),
        (photo(size=(600, 200), fmt="PNG"), 422, "image_too_small"),
    ],
    ids=["too_large", "gif", "text", "truncated", "narrow_jpeg", "short_png"],
)
def test_image_errors_save_nothing(
    client, member_token, farm: FarmSetup, db, predictor, image, status, code
) -> None:
    response = scan(client, member_token, {"cycle_id": farm.cycle_ids["Field A"]}, image=image)

    assert response.status_code == status
    assert response.json() == {"detail": {"code": code}}
    assert diagnosis_count(db) == 0
    assert leaf_files() == []
    assert predictor.seen == []


def test_png_is_stored_as_png(client, member_token, farm: FarmSetup, predictor) -> None:
    image = photo(size=(224, 224), fmt="PNG")
    response = scan(
        client,
        member_token,
        {"cycle_id": farm.cycle_ids["Field A"]},
        image=image,
        filename="leaf.jpg",  # the content decides, not the name
        mime="image/jpeg",
    )

    assert response.status_code == 201
    got = client.get(
        f"{URL}/{response.json()['diagnosis_id']}/image", headers=auth_header(member_token)
    )
    assert got.headers["content-type"] == "image/png"
    assert got.content == image


def test_photo_is_removed_when_the_row_cannot_be_saved(
    client, member_token, farm: FarmSetup, db, predictor, monkeypatch
) -> None:
    def failing_commit(self) -> None:
        raise RuntimeError("database went away")

    # Only the failing commit is undone afterwards; monkeypatch.undo() would also undo the
    # autouse fixture's temporary leaf_image_dir and look at the real backend/var folder.
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", failing_commit)
        with pytest.raises(RuntimeError):
            scan(client, member_token, {"cycle_id": farm.cycle_ids["Field A"]})

    assert diagnosis_count(db) == 0
    assert leaf_files() == []


# ---------- Reads ----------


def test_get_returns_the_saved_result_with_current_disease_text(
    client, member_token, farm: FarmSetup, db, predictor
) -> None:
    disease = add_disease(db, "Corn", "corn_test_blight")
    predictor.label = "corn_test_blight"
    created = scan(client, member_token, {"cycle_id": farm.cycle_ids["Field A"]}).json()
    disease.description_en = "Corrected description"
    db.commit()

    response = client.get(f"{URL}/{created['diagnosis_id']}", headers=auth_header(member_token))

    assert response.status_code == 200
    body = response.json()
    assert body["disease"]["description_en"] == "Corrected description"
    assert {k: v for k, v in body.items() if k != "disease"} == {
        k: v for k, v in created.items() if k != "disease"
    }


def test_image_is_returned_to_its_owner(client, member_token, farm: FarmSetup, predictor) -> None:
    created = scan(client, member_token, {"cycle_id": farm.cycle_ids["Field A"]}).json()

    response = client.get(
        f"{URL}/{created['diagnosis_id']}/image", headers=auth_header(member_token)
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == photo()


def test_another_users_scan_is_not_found(
    client, member_token, worker_token, farm: FarmSetup, predictor
) -> None:
    created = scan(client, member_token, {"cycle_id": farm.cycle_ids["Field A"]}).json()
    diagnosis_id = created["diagnosis_id"]

    for path in (f"{URL}/{diagnosis_id}", f"{URL}/{diagnosis_id}/image", f"{URL}/99999"):
        response = client.get(path, headers=auth_header(worker_token))
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "diagnosis_not_found"}}
    assert client.get(URL, headers=auth_header(worker_token)).json() == []


def test_image_missing(client, member_token, farm: FarmSetup, db, predictor) -> None:
    created = scan(client, member_token, {"cycle_id": farm.cycle_ids["Field A"]}).json()
    for file in leaf_files():
        file.unlink()

    response = client.get(
        f"{URL}/{created['diagnosis_id']}/image", headers=auth_header(member_token)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "image_missing"}}


def test_history_is_newest_first_with_paging(
    client, member_token, farm: FarmSetup, db, predictor
) -> None:
    add_disease(db, "Corn", "corn_test_blight")
    ids = []
    for label in ("corn_healthy", "corn_test_blight", "corn_unknown"):
        predictor.label = label
        ids.append(scan(client, member_token, {"cycle_id": farm.cycle_ids["Field A"]}).json())
    ids = [created["diagnosis_id"] for created in ids]

    listed = client.get(URL, headers=auth_header(member_token)).json()

    assert [item["diagnosis_id"] for item in listed] == ids[::-1]
    newest = listed[0]
    assert newest["result_status"] == "unrecognized"
    assert newest["field_name"] == "Field A"
    assert newest["crop_name"] == "Corn"
    assert listed[1]["disease_name"] == "Test condition corn_test_blight"
    assert listed[1]["local_name"] == "Test local name"

    first = client.get(f"{URL}?limit=2", headers=auth_header(member_token)).json()
    rest = client.get(f"{URL}?limit=2&offset=2", headers=auth_header(member_token)).json()
    assert [item["diagnosis_id"] for item in first + rest] == ids[::-1]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_history_paging_limits(client, member_token, query) -> None:
    response = client.get(f"{URL}?{query}", headers=auth_header(member_token))

    assert response.status_code == 422


# ---------- GET /diseases ----------


def test_diseases_list_is_empty_until_imported(client, member_token) -> None:
    response = client.get("/api/v1/diseases", headers=auth_header(member_token))

    assert response.status_code == 200
    assert response.json() == []


def test_diseases_list_with_step_counts_and_crop_filter(client, member_token, db) -> None:
    corn = add_disease(db, "Corn", "corn_test_blight", steps=(1, 2))
    add_disease(db, "Rice", "rice_test_blight", steps=(1,))

    listed = client.get("/api/v1/diseases", headers=auth_header(member_token)).json()
    corn_only = client.get(
        f"/api/v1/diseases?crop_id={corn.crop_id}", headers=auth_header(member_token)
    ).json()

    assert {(d["model_class_label"], d["treatment_count"]) for d in listed} == {
        ("corn_test_blight", 2),
        ("rice_test_blight", 1),
    }
    assert [d["model_class_label"] for d in corn_only] == ["corn_test_blight"]
    assert corn_only[0]["crop_name"] == "Corn"
    assert corn_only[0]["pathogen_type"] == "fungal"


def test_diseases_unknown_crop(client, member_token) -> None:
    response = client.get("/api/v1/diseases?crop_id=999", headers=auth_header(member_token))

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "crop_not_found"}}
