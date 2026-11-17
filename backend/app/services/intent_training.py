"""Offline training of the chatbot's intent model (Section 6, "Chatbot runtime (Phase 12)";
train-intents). Runs on the developer's machine; the API never trains (D12).

The model takes the raw question: a TextVectorization layer lowercases it, strips punctuation,
and turns it into a TF-IDF bag of words and word pairs, followed by a small dense network with
a softmax over the intent tags. 20% of each intent's examples are held out for the reported
accuracy, and every random step uses a fixed seed, so the same file gives the same model.
"""

import json
import random
from dataclasses import dataclass
from pathlib import Path

from app.services.chat_model import valid_tag
from app.services.intent_service import ImportFileError, read_csv

EXAMPLE_COLUMNS = ["intent_tag", "example_text"]
MIN_EXAMPLES = 10
HELD_OUT_SHARE = 0.2
SEED = 42
EPOCHS = 200
BATCH_SIZE = 16
HIDDEN_UNITS = 64
DROPOUT = 0.3
MODEL_FILE = "intent_model.keras"
LABELS_FILE = "labels.json"


class TensorFlowMissing(RuntimeError):
    """TensorFlow is not installed in this environment."""


@dataclass(frozen=True)
class Example:
    text: str
    tag: str


@dataclass
class TrainingReport:
    labels: list[str]
    train_count: int
    test_count: int
    accuracy: float
    right_confidence: tuple[float, float] | None  # lowest and highest
    wrong_confidence: tuple[float, float] | None
    mistakes: list[tuple[str, str, str, float]]  # text, expected tag, predicted tag, confidence
    model_path: Path
    labels_path: Path


def read_examples(path: Path) -> list[Example]:
    """The examples, checked: valid tags, non-empty text, at least 10 per intent, at least two
    intents. Raises ImportFileError listing the problems."""
    errors: list[str] = []
    examples: list[Example] = []
    for line, row in read_csv(path, EXAMPLE_COLUMNS):
        if not valid_tag(row["intent_tag"]):
            errors.append(f"{path.name} line {line}: intent_tag {row['intent_tag']!r} is not valid")
        elif not row["example_text"]:
            errors.append(f"{path.name} line {line}: example_text is required")
        else:
            examples.append(Example(row["example_text"], row["intent_tag"]))
    counts: dict[str, int] = {}
    for example in examples:
        counts[example.tag] = counts.get(example.tag, 0) + 1
    for tag, count in sorted(counts.items()):
        if count < MIN_EXAMPLES:
            errors.append(f"{path.name}: {tag!r} has {count} examples; at least {MIN_EXAMPLES}")
    if not errors and len(counts) < 2:
        errors.append(f"{path.name}: at least two intents are needed")
    if errors:
        raise ImportFileError(errors[:20])
    return examples


def split(examples: list[Example]) -> tuple[list[Example], list[Example]]:
    """Hold out 20% of each intent's examples (at least one), with a fixed seed."""
    rng = random.Random(SEED)
    train, test = [], []
    for tag in sorted({e.tag for e in examples}):
        group = [e for e in examples if e.tag == tag]
        rng.shuffle(group)
        held = max(1, round(len(group) * HELD_OUT_SHARE))
        test.extend(group[:held])
        train.extend(group[held:])
    return train, test


def _range(values: list[float]) -> tuple[float, float] | None:
    return (min(values), max(values)) if values else None


def train(examples_csv: Path, out_dir: Path) -> TrainingReport:
    """Train, save intent_model.keras and labels.json to out_dir, reload the saved model and
    score it on the held-out examples. Raises ImportFileError or TensorFlowMissing."""
    examples = read_examples(examples_csv)
    try:
        import numpy as np
        import tensorflow as tf
        from tensorflow import keras
    except ImportError as exc:
        raise TensorFlowMissing from exc

    keras.utils.set_random_seed(SEED)
    tf.config.experimental.enable_op_determinism()

    labels = sorted({e.tag for e in examples})
    index = {tag: i for i, tag in enumerate(labels)}
    train_set, test_set = split(examples)

    vectorize = keras.layers.TextVectorization(
        standardize="lower_and_strip_punctuation", ngrams=2, output_mode="tf_idf"
    )
    vectorize.adapt(np.array([e.text for e in train_set]))
    inputs = keras.Input(shape=(1,), dtype="string")
    x = vectorize(inputs)
    x = keras.layers.Dropout(DROPOUT)(x)
    x = keras.layers.Dense(HIDDEN_UNITS, activation="relu")(x)
    x = keras.layers.Dropout(DROPOUT)(x)
    outputs = keras.layers.Dense(len(labels), activation="softmax")(x)
    model = keras.Model(inputs, outputs)
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(
        np.array([[e.text] for e in train_set]),
        np.array([index[e.tag] for e in train_set]),
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        shuffle=True,
        verbose=0,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / MODEL_FILE
    labels_path = out_dir / LABELS_FILE
    model.save(model_path)
    labels_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")

    # Score the saved file, so the report also proves it loads the way the API loads it.
    saved = keras.models.load_model(model_path, compile=False)
    probabilities = np.asarray(saved(tf.constant([[e.text] for e in test_set]), training=False))
    right, wrong, mistakes = [], [], []
    for example, row in zip(test_set, probabilities, strict=True):
        best = int(np.argmax(row))
        confidence = float(row[best])
        if labels[best] == example.tag:
            right.append(confidence)
        else:
            wrong.append(confidence)
            mistakes.append((example.text, example.tag, labels[best], confidence))
    return TrainingReport(
        labels=labels,
        train_count=len(train_set),
        test_count=len(test_set),
        accuracy=len(right) / len(test_set),
        right_confidence=_range(right),
        wrong_confidence=_range(wrong),
        mistakes=mistakes,
        model_path=model_path,
        labels_path=labels_path,
    )
