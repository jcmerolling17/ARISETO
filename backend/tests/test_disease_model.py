"""Loading the disease model (Section 6, "Disease detection runtime (Phase 10)") and
check-model. TensorFlow is replaced by a fake module, so these run without it installed."""

import json
import sys
from types import SimpleNamespace

import pytest

from app import cli
from app.services import disease_model
from tests.test_diagnoses import add_disease


def _settings(tmp_path, labels=None, threshold="0.7", version="mnv2-test", model=True):
    labels_path = tmp_path / "labels.json"
    if labels is not None:
        labels_path.write_text(json.dumps(labels), encoding="utf-8")
    model_path = tmp_path / "model.keras"
    if model:
        model_path.write_bytes(b"fake")
    return SimpleNamespace(
        disease_model_path=str(model_path),
        disease_labels_path=str(labels_path),
        disease_model_version=version,
        disease_confidence_threshold=threshold,
    )


def _fake_tensorflow(monkeypatch, outputs: int | None = None, error: Exception | None = None):
    class FakeModel:
        output_shape = (None, outputs)

    def load_model(path, compile=False):
        if error:
            raise error
        return FakeModel()

    fake = SimpleNamespace(keras=SimpleNamespace(models=SimpleNamespace(load_model=load_model)))
    monkeypatch.setitem(sys.modules, "tensorflow", fake)


LABELS = ["corn_healthy", "corn_test_blight", "rice_healthy"]


def test_not_configured_names_the_missing_settings() -> None:
    status = disease_model.load(
        SimpleNamespace(
            disease_model_path=None,
            disease_labels_path="labels.json",
            disease_model_version=None,
            disease_confidence_threshold="0.7",
        )
    )

    assert status.predictor is None
    assert status.reason == "not configured (DISEASE_MODEL_PATH, DISEASE_MODEL_VERSION not set)"


@pytest.mark.parametrize("threshold", ["abc", "0", "1.5", "-0.2"])
def test_bad_threshold(tmp_path, threshold) -> None:
    status = disease_model.load(_settings(tmp_path, LABELS, threshold=threshold))

    assert status.predictor is None
    assert "DISEASE_CONFIDENCE_THRESHOLD" in status.reason


def test_version_too_long(tmp_path) -> None:
    status = disease_model.load(_settings(tmp_path, LABELS, version="v" * 21))

    assert "DISEASE_MODEL_VERSION" in status.reason


@pytest.mark.parametrize(
    ("labels", "reason"),
    [
        (None, "labels file not found"),
        ({"0": "corn_healthy"}, "non-empty JSON list"),
        ([], "non-empty JSON list"),
        (["corn_healthy", "Corn_Blight"], "not shaped <crop>_<condition>"),
        (["corn_healthy", "wheat_rust"], "not shaped <crop>_<condition>"),
        (["corn_healthy", "healthy"], "not shaped <crop>_<condition>"),
        (["corn_healthy", 7], "not shaped <crop>_<condition>"),
        (["corn_healthy", "corn_healthy"], "more than once"),
    ],
)
def test_bad_labels_file(tmp_path, labels, reason) -> None:
    status = disease_model.load(_settings(tmp_path, labels))

    assert status.predictor is None
    assert reason in status.reason


def test_unreadable_labels_json(tmp_path) -> None:
    settings = _settings(tmp_path, LABELS)
    (tmp_path / "labels.json").write_text("[not json", encoding="utf-8")

    assert "not readable JSON" in disease_model.load(settings).reason


def test_missing_model_file(tmp_path) -> None:
    status = disease_model.load(_settings(tmp_path, LABELS, model=False))

    assert "model file not found" in status.reason
    assert status.labels == tuple(LABELS)


def test_tensorflow_not_installed(tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "tensorflow", None)  # import raises ImportError

    status = disease_model.load(_settings(tmp_path, LABELS))

    assert status.predictor is None
    assert "TensorFlow is not installed" in status.reason


def test_model_that_fails_to_load(tmp_path, monkeypatch) -> None:
    _fake_tensorflow(monkeypatch, error=ValueError("bad file"))

    assert disease_model.load(_settings(tmp_path, LABELS)).reason == (
        "model file failed to load: ValueError"
    )


def test_label_count_must_match_the_model_outputs(tmp_path, monkeypatch) -> None:
    _fake_tensorflow(monkeypatch, outputs=4)

    status = disease_model.load(_settings(tmp_path, LABELS))

    assert status.predictor is None
    assert status.reason == "the model has 4 outputs but labels.json has 3 labels"


def test_loads_with_matching_labels_and_no_onion(tmp_path, monkeypatch) -> None:
    _fake_tensorflow(monkeypatch, outputs=3)

    status = disease_model.load(_settings(tmp_path, LABELS, threshold="0.85"))

    assert status.reason is None
    assert status.predictor.version == "mnv2-test"
    assert status.predictor.threshold == 0.85


# ---------- check-model ----------


def _use_settings(monkeypatch, settings) -> None:
    real = cli.disease_model.load
    monkeypatch.setattr(cli.disease_model, "load", lambda: real(settings))


def test_check_model_not_configured(monkeypatch, capsys) -> None:
    assert cli.main(["check-model"]) == 1

    out = capsys.readouterr().out
    assert "Model not loaded: not configured" in out


def test_check_model_reports_the_reason_and_labels_without_rows(
    tmp_path, monkeypatch, capsys, db
) -> None:
    add_disease(db, "Corn", "corn_test_blight")
    _use_settings(monkeypatch, _settings(tmp_path, LABELS + ["rice_test_spot"], model=False))

    assert cli.main(["check-model"]) == 1

    out = capsys.readouterr().out
    assert "Model not loaded: model file not found" in out
    assert "Labels: 4." in out
    assert "Healthy classes: corn_healthy, rice_healthy." in out
    assert "Labels with no DISEASE row (1; scanned as unrecognized):\n  rice_test_spot" in out


def test_check_model_loaded(tmp_path, monkeypatch, capsys, db) -> None:
    add_disease(db, "Corn", "corn_test_blight")
    _fake_tensorflow(monkeypatch, outputs=3)
    _use_settings(monkeypatch, _settings(tmp_path, LABELS))

    assert cli.main(["check-model"]) == 0

    out = capsys.readouterr().out
    assert "Model loaded: version mnv2-test, threshold 0.7." in out
    assert "Every disease label has a DISEASE row." in out
