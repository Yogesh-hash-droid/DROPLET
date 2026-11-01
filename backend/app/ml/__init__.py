"""ML inference package (Phase 5): advisory potability predictions."""
from app.ml.service import (
    FEATURE_COLUMNS,
    ML_DISCLAIMER,
    ML_STATUS,
    MLInferenceResult,
    MLServiceError,
    get_ml_service,
    predict_reading,
    set_ml_service,
)

__all__ = [
    "FEATURE_COLUMNS",
    "ML_DISCLAIMER",
    "ML_STATUS",
    "MLInferenceResult",
    "MLServiceError",
    "get_ml_service",
    "predict_reading",
    "set_ml_service",
]
