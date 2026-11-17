"""The chatbot's intent model (DFD 6.2; Section 6, "Chatbot runtime (Phase 12)"), loaded once
at startup behind a small Predictor interface, like the disease model.

The .keras file does its own text preprocessing, so it takes the raw question. TensorFlow is
imported only when all four CHATBOT_* settings are set. When one is missing, or the labels or
the model fail to load, the API still starts, one warning is logged, and POST /chat/messages
answers 503 model_unavailable; check-chatbot reports the reason.
"""

import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import Settings, get_settings
from app.services.disease_model import ModelLoadError, Prediction

logger = logging.getLogger("app.chat")

VERSION_MAX_LENGTH = 20
TAG_MAX_LENGTH = 80  # CHAT_INTENT.intent_tag
TAG_PATTERN = re.compile(r"^[a-z0-9_]+$")

SETTING_NAMES = {
    "chatbot_model_path": "CHATBOT_MODEL_PATH",
    "chatbot_labels_path": "CHATBOT_LABELS_PATH",
    "chatbot_model_version": "CHATBOT_MODEL_VERSION",
    "chatbot_confidence_threshold": "CHATBOT_CONFIDENCE_THRESHOLD",
}


class Predictor(Protocol):
    version: str
    threshold: float

    def predict(self, text: str) -> Prediction:
        """The most likely intent tag for a question."""
        ...


@dataclass(frozen=True)
class ModelStatus:
    predictor: Predictor | None
    reason: str | None = None
    labels: tuple[str, ...] | None = None


@dataclass(frozen=True)
class _Config:
    model_path: Path
    labels_path: Path
    version: str
    threshold: float


def _read_config(settings: Settings) -> _Config:
    missing = [env for attr, env in SETTING_NAMES.items() if getattr(settings, attr) is None]
    if missing:
        raise ModelLoadError(f"not configured ({', '.join(missing)} not set)")
    try:
        threshold = float(settings.chatbot_confidence_threshold)
    except ValueError:
        threshold = -1.0
    if not 0 < threshold <= 1:
        raise ModelLoadError("CHATBOT_CONFIDENCE_THRESHOLD must be a number above 0, up to 1")
    version = settings.chatbot_model_version
    if len(version) > VERSION_MAX_LENGTH:
        raise ModelLoadError(
            f"CHATBOT_MODEL_VERSION must be at most {VERSION_MAX_LENGTH} characters"
        )
    return _Config(
        Path(settings.chatbot_model_path), Path(settings.chatbot_labels_path), version, threshold
    )


def valid_tag(tag: object) -> bool:
    """Lowercase letters, digits and underscores, at most 80 characters."""
    return isinstance(tag, str) and len(tag) <= TAG_MAX_LENGTH and bool(TAG_PATTERN.fullmatch(tag))


def read_labels(path: Path) -> tuple[str, ...]:
    """The intent tags in output order: a plain JSON list of strings."""
    try:
        labels = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelLoadError(f"labels file not found: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelLoadError(f"labels file is not readable JSON: {path}") from exc
    if not isinstance(labels, list) or not labels:
        raise ModelLoadError("labels file must be a non-empty JSON list of strings")
    bad = [label for label in labels if not valid_tag(label)]
    if bad:
        shown = ", ".join(repr(label) for label in bad[:5])
        raise ModelLoadError(f"labels are not intent tags (a-z, 0-9, _): {shown}")
    if len(set(labels)) != len(labels):
        raise ModelLoadError("labels file lists a label more than once")
    return tuple(labels)


class KerasPredictor:
    """A loaded Keras text classifier; predictions are serialized across request threads."""

    def __init__(self, model, labels: tuple[str, ...], version: str, threshold: float):
        self._model = model
        self._labels = labels
        self._lock = threading.Lock()
        self.version = version
        self.threshold = threshold

    def predict(self, text: str) -> Prediction:
        import numpy as np
        import tensorflow as tf

        with self._lock:
            probabilities = np.asarray(self._model(tf.constant([[text]]), training=False))[0]
        index = int(np.argmax(probabilities))
        confidence = float(probabilities[index])
        if not 0 <= confidence <= 1:
            raise RuntimeError("the intent model's output is not a probability")
        return Prediction(self._labels[index], confidence)


def load(settings: Settings | None = None) -> ModelStatus:
    """Load the intent model and labels; never raises."""
    settings = settings or get_settings()
    labels = None
    try:
        config = _read_config(settings)
        labels = read_labels(config.labels_path)
        if not config.model_path.is_file():
            raise ModelLoadError(f"model file not found: {config.model_path}")
        try:
            import tensorflow as tf
        except ImportError as exc:
            raise ModelLoadError(
                'TensorFlow is not installed (pip install -e ".[ml]" in backend)'
            ) from exc
        try:
            model = tf.keras.models.load_model(config.model_path, compile=False)
        except Exception as exc:  # any failure inside Keras means the file can't be used
            raise ModelLoadError(f"model file failed to load: {type(exc).__name__}") from exc
        shape = model.output_shape
        if isinstance(shape, list):
            raise ModelLoadError("the model must have exactly one output")
        if int(shape[-1]) != len(labels):
            raise ModelLoadError(
                f"the model has {shape[-1]} outputs but labels.json has {len(labels)} labels"
            )
    except ModelLoadError as exc:
        return ModelStatus(predictor=None, reason=str(exc), labels=labels)
    return ModelStatus(
        predictor=KerasPredictor(model, labels, config.version, config.threshold),
        labels=labels,
    )


_status: ModelStatus | None = None
_status_lock = threading.Lock()


def load_at_startup() -> ModelStatus:
    """Load once (API startup); logs one warning when the chatbot is off."""
    global _status
    with _status_lock:
        _status = load()
        if _status.predictor is None:
            logger.warning("Chatbot is off: %s", _status.reason)
        return _status


def current() -> ModelStatus:
    """The loaded status; loads on first use when startup did not run."""
    return _status if _status is not None else load_at_startup()


def reset() -> None:
    """Forget the loaded model, so the next current() loads again (used by the tests)."""
    global _status
    with _status_lock:
        _status = None
