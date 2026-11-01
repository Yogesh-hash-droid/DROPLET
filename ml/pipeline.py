"""
Shared, reproducible ML pipeline for Phase 4 (Water Potability prediction).

Dataset: "Water Potability" (Kaggle, Aditya Kadiwal) - real labelled water samples.
Selected ML features (must match the project's sensor architecture):
    ph      -> dataset column "ph"       (pH units, 0-14)
    tds     -> dataset column "Solids"   (Total Dissolved Solids, ppm == mg/L)
    turbidity -> dataset column "Turbidity" (NTU)
Temperature is NOT used by the ML model: the labelled dataset contains no
temperature measurement, and no temperature value is ever fabricated or renamed.
The Safety Rule Engine (Phase 3) remains independent and continues to use all
four sensor readings including temperature.

Target: dataset column "Potability" (0 = NOT POTABLE, 1 = POTABLE).
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

# --------------------------------------------------------------------------
# Configuration (paths + training configuration)
# --------------------------------------------------------------------------
ML_ROOT = Path(__file__).resolve().parent
REPO_ROOT = ML_ROOT.parent
DATA_DIR = ML_ROOT / "data"
MODEL_DIR = ML_ROOT / "models"
DATASET_PATH = DATA_DIR / "water_potability.csv"
MODEL_PATH = MODEL_DIR / "water_potability_model.joblib"

DATASET_NAME = "Water Potability"
DATASET_KAGGLE_URL = "https://www.kaggle.com/datasets/adityakadiwal/water-potability"
DATASET_MIRROR_URL = (
    "https://raw.githubusercontent.com/Sarthak-1408/Water-Potability/main/water_potability.csv"
)
DATASET_SHA256 = "904004bde729bfe3d2e195f46343bceead09e32a0eb95bb8184e7e20e029b2bf"

RANDOM_SEED = 42
TEST_SIZE = 0.2
N_ESTIMATORS = 200
# A small, a-priori candidate grid. Selection is performed with 5-fold
# cross-validation on the TRAINING split only (ROC-AUC, not accuracy), so the
# held-out test set is never used to pick a model.
CANDIDATE_MODELS: List[Dict[str, Any]] = [
    {"n_estimators": N_ESTIMATORS, "max_depth": None, "min_samples_leaf": 1},
    {"n_estimators": N_ESTIMATORS, "max_depth": 8, "min_samples_leaf": 1},
    {"n_estimators": N_ESTIMATORS, "max_depth": 8, "min_samples_leaf": 5},
    {"n_estimators": N_ESTIMATORS, "max_depth": 12, "min_samples_leaf": 3},
]

# Canonical project feature names -> dataset source columns.
# "Solids" is the dataset's Total Dissolved Solids measurement (ppm); no
# unrelated column is renamed or repurposed.
FEATURE_TO_SOURCE: Dict[str, str] = {"ph": "ph", "tds": "Solids", "turbidity": "Turbidity"}
# Inverse map used when renaming the raw dataset columns to project names.
SOURCE_TO_FEATURE: Dict[str, str] = {
    source: feature for feature, source in FEATURE_TO_SOURCE.items()
}
FEATURE_COLUMNS: List[str] = ["ph", "tds", "turbidity"]
TARGET_COLUMN: str = "Potability"
REQUIRED_RAW_COLUMNS: List[str] = ["ph", "Solids", "Turbidity", "Potability"]
# Dataset columns that exist but are NOT used (no matching sensor on our device).
UNUSED_RAW_COLUMNS: List[str] = [
    "Hardness",
    "Chloramines",
    "Sulfate",
    "Conductivity",
    "Organic_carbon",
    "Trihalomethanes",
]

LABELS: Dict[int, str] = {0: "NOT POTABLE", 1: "POTABLE"}
# Physically plausible ranges used only to reject invalid rows (no value edits).
PHYSICAL_RANGES: Dict[str, Tuple[float, Optional[float]]] = {
    "ph": (0.0, 14.0),
    "tds": (0.0, None),
    "turbidity": (0.0, None),
}


# --------------------------------------------------------------------------
# Dataset acquisition / loading
# --------------------------------------------------------------------------
def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_dataset(path: Path = DATASET_PATH, url: str = DATASET_MIRROR_URL) -> Path:
    """Download the dataset if absent and verify its SHA-256 checksum."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, path)
    checksum = sha256_of(path)
    if checksum != DATASET_SHA256:
        raise ValueError(
            f"Dataset checksum mismatch for {path}: expected {DATASET_SHA256}, got {checksum}"
        )
    return path


def load_dataset(path: Path = DATASET_PATH) -> pd.DataFrame:
    """Load the raw dataset and validate that required columns exist."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}. Run ml/train.py to download it.")
    frame = pd.read_csv(path)
    missing = [column for column in REQUIRED_RAW_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")
    return frame


# --------------------------------------------------------------------------
# Preprocessing (deterministic, no fabricated values)
# --------------------------------------------------------------------------
def preprocess(raw: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Reproducible cleaning of the raw dataset.

    Steps (in order, no data is invented):
      1. keep only the selected sensor features + target (column mapping documented)
      2. coerce values to numeric (non-numeric -> NaN -> removed)
      3. drop rows outside physically valid ranges
      4. drop rows with missing feature/target values (listwise deletion)
      5. drop exact duplicate rows
      6. drop rows whose identical feature vector carries conflicting labels
      7. encode target as int 0/1
    """
    frame = raw.copy()
    raw_rows = int(len(frame))

    selected = frame[REQUIRED_RAW_COLUMNS].rename(columns=SOURCE_TO_FEATURE)
    selected["target"] = pd.to_numeric(selected[TARGET_COLUMN], errors="coerce")
    selected = selected.drop(columns=[TARGET_COLUMN])
    for column in FEATURE_COLUMNS:
        selected[column] = pd.to_numeric(selected[column], errors="coerce")

    non_numeric_rows = int(selected[FEATURE_COLUMNS + ["target"]].isna().sum().sum())

    valid_mask = pd.Series(True, index=selected.index)
    for column, (lower, upper) in PHYSICAL_RANGES.items():
        valid_mask &= selected[column].between(lower, upper if upper is not None else np.inf)
    valid_mask &= selected["target"].isin([0, 1])
    invalid_range_rows = int((~valid_mask).sum())
    selected = selected[valid_mask]

    missing_rows = int(selected[FEATURE_COLUMNS + ["target"]].isna().any(axis=1).sum())
    selected = selected.dropna(subset=FEATURE_COLUMNS + ["target"])

    duplicate_rows = int(selected.duplicated().sum())
    selected = selected.drop_duplicates()

    label_conflicts = int(
        (selected.groupby(FEATURE_COLUMNS)["target"].nunique() > 1).sum()
    )
    if label_conflicts:
        conflicting = selected.groupby(FEATURE_COLUMNS)["target"].transform("nunique") > 1
        selected = selected[~conflicting]

    selected["target"] = selected["target"].astype(int)
    selected = selected.reset_index(drop=True)

    class_counts = selected["target"].value_counts().to_dict()
    report: Dict[str, Any] = {
        "raw_rows": raw_rows,
        "non_numeric_cells": non_numeric_rows,
        "dropped_invalid_range_rows": invalid_range_rows,
        "dropped_missing_rows": missing_rows,
        "dropped_duplicate_rows": duplicate_rows,
        "dropped_label_conflict_rows": label_conflicts,
        "modelled_rows": int(len(selected)),
        "class_counts": {int(key): int(value) for key, value in class_counts.items()},
        "unused_dataset_columns": list(UNUSED_RAW_COLUMNS),
        "feature_columns": list(FEATURE_COLUMNS),
        "temperature_used": False,
    }
    return selected, report


def split_data(
    frame: pd.DataFrame, seed: int = RANDOM_SEED, test_size: float = TEST_SIZE
) -> Dict[str, Any]:
    """Stratified train/test split with a fixed seed (leakage-free, index based)."""
    from sklearn.model_selection import train_test_split

    indices = np.arange(len(frame))
    train_idx, test_idx = train_test_split(
        indices,
        test_size=test_size,
        random_state=seed,
        stratify=frame["target"].values,
    )
    features = frame[FEATURE_COLUMNS]
    target = frame["target"]
    return {
        "X_train": features.iloc[train_idx],
        "X_test": features.iloc[test_idx],
        "y_train": target.iloc[train_idx],
        "y_test": target.iloc[test_idx],
        "train_indices": train_idx.tolist(),
        "test_indices": test_idx.tolist(),
    }


def build_model(seed: int = RANDOM_SEED, **params: Any) -> RandomForestClassifier:
    """
    Random Forest classifier.

    class_weight is intentionally left at default: the majority class is
    NOT POTABLE, so the un-weighted model is biased towards the conservative
    (do not declare potable) direction, which is the safe failure mode for a
    water-safety application. Class imbalance is measured and documented
    instead of being hidden by re-weighting or resampling.
    """
    options: Dict[str, Any] = {"n_estimators": N_ESTIMATORS}
    options.update(params)
    return RandomForestClassifier(random_state=seed, n_jobs=1, **options)


def select_model(
    X_train: pd.DataFrame, y_train: pd.Series, seed: int = RANDOM_SEED
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Pick hyper-parameters by 5-fold CV ROC-AUC on the training split only."""
    from sklearn.model_selection import StratifiedKFold, cross_val_score

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    trials: List[Dict[str, Any]] = []
    for params in CANDIDATE_MODELS:
        scores = cross_val_score(
            build_model(seed, **params),
            X_train,
            y_train,
            cv=cv,
            scoring="roc_auc",
        )
        trials.append(
            {
                "params": params,
                "cv_roc_auc_mean": float(scores.mean()),
                "cv_roc_auc_std": float(scores.std()),
            }
        )
    best = max(trials, key=lambda item: item["cv_roc_auc_mean"])
    return dict(best["params"]), trials


def compute_metrics(model: RandomForestClassifier, X_test: pd.DataFrame, y_test: pd.Series) -> Dict[str, Any]:
    """Compute the full evaluation report on an independent test set."""
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    matrix = confusion_matrix(y_test, y_pred, labels=[0, 1])
    tn, fp, fn, tp = (int(value) for value in matrix.ravel())
    return {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "precision_potable": float(precision_score(y_test, y_pred, pos_label=1, zero_division=0)),
        "recall_potable": float(recall_score(y_test, y_pred, pos_label=1, zero_division=0)),
        "f1_potable": float(f1_score(y_test, y_pred, pos_label=1, zero_division=0)),
        "precision_macro": float(precision_score(y_test, y_pred, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_test, y_pred, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(y_test, y_pred, average="macro", zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, y_proba)),
        "confusion_matrix": {
            "tn": tn,
            "fp": fp,
            "fn": fn,
            "tp": tp,
        },
        "test_rows": int(len(y_test)),
    }


def train(
    frame: Optional[pd.DataFrame] = None,
    seed: int = RANDOM_SEED,
    path: Path = DATASET_PATH,
) -> Dict[str, Any]:
    """
    Full training routine: load -> preprocess -> split -> CV select -> fit -> evaluate.

    The held-out test split is touched exactly once, after model selection.
    """
    if frame is None:
        ensure_dataset(path)
        frame = load_dataset(path)
    clean, report = preprocess(frame)
    split = split_data(clean, seed=seed)
    params, trials = select_model(split["X_train"], split["y_train"], seed=seed)
    model = build_model(seed, **params)
    model.fit(split["X_train"], split["y_train"])
    metrics = compute_metrics(model, split["X_test"], split["y_test"])
    importances = {
        column: float(value)
        for column, value in zip(FEATURE_COLUMNS, model.feature_importances_)
    }
    return {
        "model": model,
        "split": split,
        "report": report,
        "metrics": metrics,
        "feature_importances": importances,
        "seed": seed,
        "selected_params": params,
        "selection_trials": trials,
    }


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------
def save_artifacts(payload: Dict[str, Any], path: Path = MODEL_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, path)
    return path


def load_artifacts(path: Path = MODEL_PATH) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Model artifact not found: {path}. Train the model first (python ml/train.py)."
        )
    payload = joblib.load(path)
    if not isinstance(payload, dict) or "model" not in payload:
        raise ValueError(f"Unexpected artifact format in {path}")
    return payload


# --------------------------------------------------------------------------
# Inference
# --------------------------------------------------------------------------
def validate_record(record: Dict[str, Any]) -> Dict[str, float]:
    """Validate a single sensor record before inference (no NaN, in range)."""
    missing = [column for column in FEATURE_COLUMNS if column not in record]
    if missing:
        raise ValueError(f"Missing feature(s): {missing}")
    values: Dict[str, float] = {}
    for column in FEATURE_COLUMNS:
        value = record[column]
        if value is None:
            raise ValueError(f"Feature '{column}' is null")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Feature '{column}' is not numeric: {value!r}") from exc
        if not np.isfinite(number):
            raise ValueError(f"Feature '{column}' is not finite: {number}")
        lower, upper = PHYSICAL_RANGES[column]
        if number < lower or (upper is not None and number > upper):
            raise ValueError(
                f"Feature '{column}'={number} outside valid range [{lower}, {upper}]"
            )
        values[column] = number
    return values


def predict_record(payload: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    """Predict POTABLE / NOT POTABLE for one record with a [0, 1] confidence."""
    model = payload["model"]
    labels = payload.get("labels", LABELS)
    values = validate_record(record)
    frame = pd.DataFrame([values], columns=FEATURE_COLUMNS)
    class_index = int(model.predict(frame)[0])
    probabilities = model.predict_proba(frame)[0]
    confidence = float(probabilities[class_index])
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"Confidence out of range: {confidence}")
    return {
        "prediction": labels[class_index],
        "confidence": round(confidence, 6),
        "probabilities": {
            labels[0]: round(float(probabilities[0]), 6),
            labels[1]: round(float(probabilities[1]), 6),
        },
        "features": values,
    }


def format_metrics(metrics: Dict[str, Any]) -> str:
    """Human readable metrics report."""
    matrix = metrics["confusion_matrix"]
    lines = [
        f"Accuracy            : {metrics['accuracy']:.4f}",
        f"Precision (POTABLE) : {metrics['precision_potable']:.4f}",
        f"Recall    (POTABLE) : {metrics['recall_potable']:.4f}",
        f"F1-score  (POTABLE) : {metrics['f1_potable']:.4f}",
        f"F1-score  (macro)   : {metrics['f1_macro']:.4f}",
        f"ROC-AUC             : {metrics['roc_auc']:.4f}",
        "Confusion matrix    :",
        f"  TN={matrix['tn']}  FP={matrix['fp']}",
        f"  FN={matrix['fn']}  TP={matrix['tp']}",
        f"  (rows=actual [NOT POTABLE, POTABLE], cols=predicted [NOT POTABLE, POTABLE])",
    ]
    return "\n".join(lines)


def dump_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=False)
