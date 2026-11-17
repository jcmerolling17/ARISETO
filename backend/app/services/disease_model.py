"""The disease detection model (DFD 3.3-3.4; Section 6, "Disease detection runtime (Phase
10)"), loaded once at startup behind a small Predictor interface.

TensorFlow is imported only when all four DISEASE_* settings are set. When one is missing,
or the labels or the model fail to load, the API still starts, one warning is logged, and
POST /diagnoses answers 503 model_unavailable; check-model reports the reason.
"""

import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image

from app.core.config import Settings, get_settings
from app.core.constants import CROPS_IN_SCOPE

logger = logging.getLogger("app.disease")

# The model takes the whole photo resized to 224 x 224 RGB, values 0 to 255, and does its own
# preprocessing (as Keras image_dataset_from_directory feeds it in training: no cropping).
INPUT_SIZE = (224, 224)
VERSION_MAX_LENGTH = 20  # DIAGNOSIS.model_version
LABEL_MAX_LENGTH = 80  # DIAGNOSIS.predicted_label
# Lowercase <crop>_<condition>, crop one of rice, corn or onion.
LABEL_PATTERN = re.compile(rf"^(?:{'|'.join(CROPS_IN_SCOPE)})_[a-z0-9_]+$")

SETTING_NAMES = {
    "disease_model_path": "DISEASE_MODEL_PATH",
    "disease_labels_path": "DISEASE_LABELS_PATH",
    "disease_model_version": "DISEASE_MODEL_VERSION",
    "disease_confidence_threshold": "DISEASE_CONFIDENCE_THRESHOLD",
}


@dataclass(frozen=True)
class Prediction:
    """The top class and its probability."""

    label: str
    confidence: float


class Predictor(Protocol):
    version: str
    threshold: float

    def predict(self, image: Image.Image) -> Prediction:
        """The top class for an RGB photo."""
        ...


class ModelLoadError(Exception):
    """Why disease detection is off; the message is shown by check-model and in the log."""


@dataclass(frozen=True)
class ModelStatus:
    predictor: Predictor | None
    reason: str | None = None
    # The labels from labels.json when they could be read, even if the model then failed.
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
        threshold = float(settings.disease_confidence_threshold)
    except ValueError:
        threshold = -1.0
    if not 0 < threshold <= 1:
        raise ModelLoadError("DISEASE_CONFIDENCE_THRESHOLD must be a number above 0, up to 1")

    version = settings.disease_model_version
    if len(version) > VERSION_MAX_LENGTH:
        raise ModelLoadError(
            f"DISEASE_MODEL_VERSION must be at most {VERSION_MAX_LENGTH} characters"
        )
    return _Config(
        Path(settings.disease_model_path), Path(settings.disease_labels_path), version, threshold
    )


def read_labels(path: Path) -> tuple[str, ...]:
    """The class labels in output order: a JSON list of lowercase <crop>_<condition> strings."""
    try:
        labels = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelLoadError(f"labels file not found: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelLoadError(f"labels file is not readable JSON: {path}") from exc

    if not isinstance(labels, list) or not labels:
        raise ModelLoadError("labels file must be a non-empty JSON list of strings")
    bad = [
        label
        for label in labels
        if not isinstance(label, str)
        or len(label) > LABEL_MAX_LENGTH
        or not LABEL_PATTERN.fullmatch(label)
    ]
    if bad:
        shown = ", ".join(repr(label) for label in bad[:5])
        raise ModelLoadError(f"labels not shaped <crop>_<condition>: {shown}")
    if len(set(labels)) != len(labels):
        raise ModelLoadError("labels file lists a label more than once")
    return tuple(labels)


class KerasPredictor:
    """A loaded Keras model. Predictions are serialized, since requests run in a thread pool."""

    def __init__(self, model, labels: tuple[str, ...], version: str, threshold: float):
        self._model = model
        self._labels = labels
        self._lock = threading.Lock()
        self.version = version
        self.threshold = threshold

    def predict(self, image: Image.Image) -> Prediction:
        import numpy as np
        import tensorflow as tf

        pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
        # Stretch the whole photo to 224 x 224 with bilinear resizing, as in training.
        batch = tf.image.resize(pixels[np.newaxis, ...], INPUT_SIZE, method="bilinear")
        with self._lock:
            probabilities = np.asarray(self._model(batch, training=False))[0]
        index = int(np.argmax(probabilities))
        confidence = float(probabilities[index])
        if not 0 <= confidence <= 1:
            raise RuntimeError("the disease model's output is not a probability")
        return Prediction(self._labels[index], confidence)


def _output_count(model) -> int:
    shape = model.output_shape
    if isinstance(shape, list):
        raise ModelLoadError("the model must have exactly one output")
    return int(shape[-1])


def load(settings: Settings | None = None) -> ModelStatus:
    """Load the model and labels; never raises."""
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
        outputs = _output_count(model)
        if outputs != len(labels):
            raise ModelLoadError(
                f"the model has {outputs} outputs but labels.json has {len(labels)} labels"
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
    """Load once (API startup); logs one warning when disease detection is off."""
    global _status
    with _status_lock:
        _status = load()
        if _status.predictor is None:
            logger.warning("Disease detection is off: %s", _status.reason)
        else:
            logger.info(
                "Disease model %s loaded with %d labels",
                _status.predictor.version,
                len(_status.labels or ()),
            )
        return _status


def current() -> ModelStatus:
    """The loaded status; loads on first use when startup did not run (e.g. a script)."""
    return _status if _status is not None else load_at_startup()


def reset() -> None:
    """Forget the loaded model, so the next current() loads again (used by the tests)."""
    global _status
    with _status_lock:
        _status = None
