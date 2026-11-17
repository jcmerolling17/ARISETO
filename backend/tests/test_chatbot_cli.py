"""Loading the intent model, check-chatbot, import-intents and train-intents (Section 6,
"Chatbot runtime (Phase 12)"). TensorFlow is replaced by a fake module where loading is
tested; real training runs only when TensorFlow is installed. Rows are made-up test data."""

import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app import cli
from app.models import ChatIntent
from app.services import chat_model, intent_training
from app.services.intent_service import INTENT_COLUMNS
from app.services.intent_training import EXAMPLE_COLUMNS

LABELS = ["test_greeting", "weather_check", "today_tasks"]


def _settings(tmp_path, labels=None, threshold="0.7", version="intent-test", model=True):
    labels_path = tmp_path / "labels.json"
    if labels is not None:
        labels_path.write_text(json.dumps(labels), encoding="utf-8")
    model_path = tmp_path / "intent_model.keras"
    if model:
        model_path.write_bytes(b"fake")
    return SimpleNamespace(
        chatbot_model_path=str(model_path),
        chatbot_labels_path=str(labels_path),
        chatbot_model_version=version,
        chatbot_confidence_threshold=threshold,
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


# ---------- Loading ----------


def test_not_configured_names_the_missing_settings() -> None:
    status = chat_model.load(
        SimpleNamespace(
            chatbot_model_path=None,
            chatbot_labels_path=None,
            chatbot_model_version="v1",
            chatbot_confidence_threshold="0.7",
        )
    )

    assert status.reason == "not configured (CHATBOT_MODEL_PATH, CHATBOT_LABELS_PATH not set)"


@pytest.mark.parametrize("threshold", ["x", "0", "1.01"])
def test_bad_threshold(tmp_path, threshold) -> None:
    status = chat_model.load(_settings(tmp_path, LABELS, threshold=threshold))

    assert "CHATBOT_CONFIDENCE_THRESHOLD" in status.reason


@pytest.mark.parametrize(
    ("labels", "reason"),
    [
        (None, "labels file not found"),
        ([], "non-empty JSON list"),
        (["test_greeting", "Bad Tag"], "not intent tags"),
        (["test_greeting", "x" * 81], "not intent tags"),
        (["test_greeting", "test_greeting"], "more than once"),
    ],
)
def test_bad_labels(tmp_path, labels, reason) -> None:
    assert reason in chat_model.load(_settings(tmp_path, labels)).reason


def test_tensorflow_not_installed(tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "tensorflow", None)

    assert "TensorFlow is not installed" in chat_model.load(_settings(tmp_path, LABELS)).reason


def test_label_count_must_match(tmp_path, monkeypatch) -> None:
    _fake_tensorflow(monkeypatch, outputs=2)

    status = chat_model.load(_settings(tmp_path, LABELS))

    assert status.reason == "the model has 2 outputs but labels.json has 3 labels"


def test_loads(tmp_path, monkeypatch) -> None:
    _fake_tensorflow(monkeypatch, outputs=3)

    status = chat_model.load(_settings(tmp_path, LABELS, threshold="0.65"))

    assert status.reason is None
    assert status.predictor.threshold == 0.65
    assert status.predictor.version == "intent-test"


# ---------- check-chatbot ----------


def _use_settings(monkeypatch, settings) -> None:
    real = cli.chat_model.load
    monkeypatch.setattr(cli.chat_model, "load", lambda: real(settings))


def test_check_chatbot_not_configured(capsys) -> None:
    assert cli.main(["check-chatbot"]) == 1
    assert "Model not loaded: not configured" in capsys.readouterr().out


def test_check_chatbot_lists_labels_without_an_active_row(
    tmp_path, monkeypatch, capsys, db
) -> None:
    db.add_all(
        [
            ChatIntent(intent_tag="test_greeting", response_en="Hi", source_reference="G"),
            ChatIntent(intent_tag="weather_check", response_en="W", is_active=False),
        ]
    )
    db.commit()
    _fake_tensorflow(monkeypatch, outputs=3)
    _use_settings(monkeypatch, _settings(tmp_path, LABELS))

    assert cli.main(["check-chatbot"]) == 0

    out = capsys.readouterr().out
    assert "Model loaded: version intent-test, threshold 0.7." in out
    assert "Labels (3): test_greeting, weather_check, today_tasks" in out
    assert (
        "no active CHAT_INTENT row (2; answered with the fallback):\n  weather_check\n  today_tasks"
        in out
    )


# ---------- import-intents ----------


def _intent(**overrides) -> dict:
    row = {
        "intent_tag": "test_greeting",
        "crop_name": "",
        "response_en": "Hello",
        "response_fil": "",
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


def _count(db) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(ChatIntent))


def test_import_adds_then_updates_and_keeps_other_rows(tmp_path, db, capsys) -> None:
    db.add(ChatIntent(intent_tag="test_kept", response_en="Kept", source_reference="G"))
    db.commit()
    rows = [
        _intent(),
        _intent(intent_tag="test_corn", crop_name="Corn", response_fil="Kumusta"),
        _intent(intent_tag="weather_check", source_reference=""),  # farm-data: no source needed
    ]
    path = _write(tmp_path / "intents.csv", INTENT_COLUMNS, rows)

    assert cli.main(["import-intents", path]) == 0
    assert "Imported 3 intents (3 added, 0 updated)." in capsys.readouterr().out

    greeting = db.scalar(select(ChatIntent).where(ChatIntent.intent_tag == "test_greeting"))
    greeting.is_active = False
    db.commit()
    path = _write(tmp_path / "intents.csv", INTENT_COLUMNS, [_intent(response_en="Hi again")])
    assert cli.main(["import-intents", path]) == 0
    assert "(0 added, 1 updated)" in capsys.readouterr().out

    db.expire_all()
    greeting = db.scalar(select(ChatIntent).where(ChatIntent.intent_tag == "test_greeting"))
    assert greeting.response_en == "Hi again"
    assert greeting.is_active is False  # an update keeps is_active
    corn = db.scalar(select(ChatIntent).where(ChatIntent.intent_tag == "test_corn"))
    assert corn.crop_id is not None and corn.response_fil == "Kumusta"
    assert _count(db) == 4  # test_kept stays


def test_dry_run_saves_nothing(tmp_path, db, capsys) -> None:
    path = _write(tmp_path / "intents.csv", INTENT_COLUMNS, [_intent()])

    assert cli.main(["import-intents", path, "--dry-run"]) == 0
    assert "Dry run, nothing saved: would import 1 intents" in capsys.readouterr().out
    assert _count(db) == 0


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([_intent(intent_tag="Bad Tag")], "must be a-z, 0-9 and _"),
        ([_intent(), _intent()], "listed twice"),
        ([_intent(crop_name="wheat")], "unknown crop_name 'wheat'"),
        ([_intent(response_en="")], "response_en is required"),
        ([_intent(source_reference="")], "source_reference is required"),
        ([_intent(source_reference="x" * 256)], "longer than 255"),
        ([], "no intents listed"),
    ],
)
def test_bad_file_saves_nothing(tmp_path, db, capsys, rows, message) -> None:
    path = _write(tmp_path / "intents.csv", INTENT_COLUMNS, [_intent(intent_tag="test_ok"), *rows])
    if not rows:
        path = _write(tmp_path / "intents.csv", INTENT_COLUMNS, [])

    assert cli.main(["import-intents", path]) == 1

    err = capsys.readouterr().err
    assert "Nothing imported:" in err and message in err
    assert _count(db) == 0


def test_wrong_header(tmp_path, capsys) -> None:
    path = _write(tmp_path / "intents.csv", ["tag", "answer"], [{"tag": "a", "answer": "b"}])

    assert cli.main(["import-intents", path]) == 1
    assert "intents.csv: expected columns intent_tag,crop_name" in capsys.readouterr().err


# ---------- train-intents ----------


def _examples(tmp_path, per_intent=10, tags=("test_a", "test_b")) -> str:
    rows = [
        {"intent_tag": tag, "example_text": f"{tag} question number {n}"}
        for tag in tags
        for n in range(per_intent)
    ]
    return _write(tmp_path / "examples.csv", EXAMPLE_COLUMNS, rows)


def test_too_few_examples_is_rejected(tmp_path, capsys) -> None:
    path = _examples(tmp_path, per_intent=9)

    assert cli.main(["train-intents", path, "--out", str(tmp_path / "out")]) == 1
    assert "'test_a' has 9 examples; at least 10" in capsys.readouterr().err


def test_one_intent_is_rejected(tmp_path, capsys) -> None:
    path = _examples(tmp_path, tags=("test_a",))

    assert cli.main(["train-intents", path, "--out", str(tmp_path / "out")]) == 1
    assert "at least two intents" in capsys.readouterr().err


def test_split_holds_out_a_fifth_of_each_intent_the_same_way_every_time(tmp_path) -> None:
    examples = intent_training.read_examples(Path(_examples(tmp_path, per_intent=15)))

    train, test = intent_training.split(examples)
    again = intent_training.split(examples)

    assert len(test) == 6 and len(train) == 24  # 3 of each 15
    assert {e.tag for e in test} == {"test_a", "test_b"}
    assert (train, test) == again


def test_train_without_tensorflow_says_so(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setitem(sys.modules, "tensorflow", None)

    assert cli.main(["train-intents", _examples(tmp_path), "--out", str(tmp_path / "out")]) == 1
    assert "TensorFlow is not installed" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_train_with_tensorflow(tmp_path, capsys) -> None:
    pytest.importorskip("tensorflow")
    out = tmp_path / "out"

    assert cli.main(["train-intents", _examples(tmp_path), "--out", str(out)]) == 0

    printed = capsys.readouterr().out
    assert "Held-out accuracy:" in printed
    assert "Confidence of right answers:" in printed
    assert json.loads((out / "labels.json").read_text(encoding="utf-8")) == ["test_a", "test_b"]
    assert (out / "intent_model.keras").is_file()
