"""
Phase 5 - ML inference service (EXPERIMENTAL / ADVISORY).

Loads the Phase 4 Random Forest artifact exactly once (lazy, thread-safe) and
returns POTABLE / NOT POTABLE with the model probability of the predicted class
as `confidence` (always in [0, 1]).

Contract:
  * Features are exactly the ones the model was trained on:
    `ph`, `tds`, `turbidity`. Temperature is NEVER passed to this model.
  * This service NEVER writes to the database and NEVER touches the Safety
    Rule Engine or the Water Quality Score. It only produces an advisory
    verdict that is stored alongside the assessment.
  * Any failure (missing artifact, corrupt artifact, invalid input, inference
    error) is surfaced as `MLServiceError` so callers can degrade gracefully -
    safety assessment keeps working and `prediction` / `confidence` stay `null`.
    No fabricated values are ever produced on failure.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import joblib
import pandas as pd

from app.config import get_settings

logger = logging.getLogger("app.ml")

# Sensor features used by the model (identical order/names as training time).
FEATURE_COLUMNS: Tuple[str, ...] = ("ph", "tds", "turbidity")
LABELS: Dict[int, str] = {0: "NOT POTABLE", 1: "POTABLE"}
# Physically valid input ranges - rejected values are never imputed or faked.
PHYSICAL_RANGES: Dict[str, Tuple[float, Optional[float]]] = {
    "ph": (0.0, 14.0),
    "tds": (0.0, None),
    "turbidity": (0.0, None),
}

ML_STATUS = "EXPERIMENTAL"
ML_DISCLAIMER = (
    "EXPERIMENTAL / ADVISORY ML prediction from a weak prototype model "
    "(test ROC-AUC 0.5522, POTABLE recall 0.0864). It is NOT a guarantee that "
    "water is safe to drink and it never overrides the Safety Rule Engine."
)


class MLServiceError(RuntimeError):
    """Raised when the model cannot be loaded or inference cannot be trusted."""


@dataclass(frozen=True)
class MLInferenceResult:
    """A single advisory potability verdict."""

    prediction: str  # "POTABLE" | "NOT POTABLE"
    confidence: float  # probability of `prediction`, in [0, 1]
    probabilities: Dict[str, float] = field(default_factory=dict)
    features: Dict[str, float] = field(default_factory=dict)
    model_trained_at: Optional[str] = None
    status: str = ML_STATUS

    def __post_init__(self) -> None:
        if self.prediction not in {"POTABLE", "NOT POTABLE"}:
            raise MLServiceError(f"Unexpected prediction label: {self.prediction!r}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise MLServiceError(f"Confidence out of [0, 1]: {self.confidence}")


def _validate_features(ph: Any, tds: Any, turbidity: Any) -> Dict[str, float]:
    """Validate the three sensor inputs (never impute, never fabricate)."""
    values = {"ph": ph, "tds": tds, "turbidity": turbidity}
    validated: Dict[str, float] = {}
    for column in FEATURE_COLUMNS:
        raw = values[column]
        if raw is None:
            raise MLServiceError(f"Feature '{column}' is null")
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise MLServiceError(f"Feature '{column}' is not numeric: {raw!r}") from exc
        if number != number or number in (float("inf"), float("-inf")):
            raise MLServiceError(f"Feature '{column}' is not finite: {number}")
        lower, upper = PHYSICAL_RANGES[column]
        if number < lower or (upper is not None and number > upper):
            raise MLServiceError(
                f"Feature '{column}'={number} outside valid range [{lower}, {upper}]"
            )
        validated[column] = number
    return validated


class MLInferenceService:
    """
    Loads the joblib artifact once and reuses it for every request.

    Thread-safe: concurrent readers share a single payload; loading happens at
    most once per process (unless `force=True` or `reset()` is called).
    """

    def __init__(self, model_path: Optional[str | Path] = None) -> None:
        self._model_path = Path(model_path or get_settings().MODEL_PATH)
        self._lock = threading.Lock()
        self._payload: Optional[Dict[str, Any]] = None
        self._last_error: Optional[str] = None

    # ---------------------------------------------------------------- state ----
    @property
    def model_path(self) -> Path:
        return self._model_path

    @property
    def is_loaded(self) -> bool:
        return self._payload is not None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def reset(self) -> None:
        """Drop the cached payload (used by tests)."""
        with self._lock:
            self._payload = None
            self._last_error = None

    # ----------------------------------------------------------------- load ----
    def load(self, force: bool = False) -> Dict[str, Any]:
        """Load (or return the cached) model payload. Raises MLServiceError."""
        if self._payload is not None and not force:
            return self._payload
        with self._lock:
            if self._payload is not None and not force:
                return self._payload
            try:
                if not self._model_path.exists():
                    raise MLServiceError(
                        f"Model artifact not found: {self._model_path}. "
                        "Train it first with `python ml/train.py`."
                    )
                payload = joblib.load(self._model_path)
                if not isinstance(payload, dict) or "model" not in payload:
                    raise MLServiceError(f"Unexpected artifact format: {self._model_path}")
                features = tuple(payload.get("feature_columns") or FEATURE_COLUMNS)
                if features != FEATURE_COLUMNS:
                    raise MLServiceError(
                        f"Artifact feature set {features} does not match the "
                        f"expected sensor features {FEATURE_COLUMNS}"
                    )
                if payload.get("temperature_used", False) is True:
                    raise MLServiceError("Artifact unexpectedly reports temperature_used=True")
                if not hasattr(payload["model"], "predict_proba"):
                    raise MLServiceError("Loaded object has no predict_proba method")
            except MLServiceError as exc:
                self._payload = None
                self._last_error = str(exc)
                logger.error("ML model load failed: %s", exc)
                raise
            except Exception as exc:  # corrupt file, unpickling error, ...
                self._payload = None
                self._last_error = f"Model load failed: {exc}"
                logger.error(self._last_error)
                raise MLServiceError(self._last_error) from exc
            self._payload = payload
            self._last_error = None
            logger.info("ML model loaded from %s", self._model_path)
            return payload

    def warm_up(self) -> bool:
        """Best-effort startup load. Never raises - API must stay available."""
        try:
            self.load()
            return True
        except Exception as exc:  # noqa: BLE001 - startup must not crash
            logger.warning("ML warm-up skipped: %s", exc)
            return False

    # -------------------------------------------------------------- predict ----
    def predict(self, ph: Any, tds: Any, turbidity: Any) -> MLInferenceResult:
        """
        Run inference on exactly `ph`, `tds`, `turbidity` (no temperature).

        Raises MLServiceError on any load/validation/inference problem.
        """
        payload = self.load()
        values = _validate_features(ph, tds, turbidity)
        model = payload["model"]
        frame = pd.DataFrame([values], columns=list(FEATURE_COLUMNS))
        try:
            raw_index = model.predict(frame)[0]
            probabilities = model.predict_proba(frame)[0]
            classes = [int(item) for item in getattr(model, "classes_", [0, 1])]
        except Exception as exc:
            raise MLServiceError(f"Model inference failed: {exc}") from exc

        index = int(raw_index)
        if index not in classes:
            raise MLServiceError(f"Model returned unknown class index: {index}")
        position = classes.index(index)
        confidence = float(probabilities[position])

        labels = {int(key): str(value) for key, value in (payload.get("labels") or LABELS).items()}
        label = labels.get(index)
        if label not in {"POTABLE", "NOT POTABLE"}:
            raise MLServiceError(f"Unmapped class index {index}")

        class_probabilities: Dict[str, float] = {}
        for position_, class_index in enumerate(classes):
            name = labels.get(class_index)
            if name in {"POTABLE", "NOT POTABLE"}:
                class_probabilities[name] = round(float(probabilities[position_]), 6)

        return MLInferenceResult(
            prediction=label,
            confidence=round(confidence, 6),
            probabilities=class_probabilities,
            features=values,
            model_trained_at=payload.get("trained_at"),
        )


# ---------------------------------------------------------------------------
# Module-level singleton: one artifact per process, shared by all requests.
# ---------------------------------------------------------------------------
_service: Optional[MLInferenceService] = None
_service_lock = threading.Lock()


def get_ml_service() -> MLInferenceService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = MLInferenceService()
    return _service


def set_ml_service(service: Optional[MLInferenceService]) -> None:
    """Replace/inject the singleton (tests only)."""
    global _service
    with _service_lock:
        _service = service


def predict_reading(ph: Any, tds: Any, turbidity: Any) -> Optional[MLInferenceResult]:
    """
    Graceful wrapper used by the reading pipeline.

    Returns `None` when the ML model cannot produce a trustworthy verdict -
    the caller then stores `prediction = NULL`, `confidence = NULL` and keeps
    the safety assessment fully functional. Failures are logged, never faked.
    """
    try:
        return get_ml_service().predict(ph=ph, tds=tds, turbidity=turbidity)
    except Exception as exc:  # noqa: BLE001 - ML must never break safety flow
        logger.error("ML inference unavailable, continuing without prediction: %s", exc)
        return None
