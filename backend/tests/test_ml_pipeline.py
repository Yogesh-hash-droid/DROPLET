"""
Phase 4 ML tests: dataset loading/validation, features, target encoding,
training, saving/loading, inference, probability ranges and reproducibility.

These tests exercise the ml/ package only; they never touch the FastAPI app,
the Safety Rule Engine or the Water Quality Score (Phase 1-3 stay unchanged).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml import pipeline, predict  # noqa: E402

SAMPLE_RECORD = {"ph": 7.2, "tds": 250.0, "turbidity": 1.5}
EXTREME_RECORDS = [
    {"ph": 0.0, "tds": 0.0, "turbidity": 0.0},
    {"ph": 14.0, "tds": 61227.196, "turbidity": 6.739},
    {"ph": 3.5, "tds": 1000.0, "turbidity": 45.0},
    {"ph": 7.037, "tds": 20927.834, "turbidity": 3.955},
]

REQUIRED_METRIC_KEYS = {
    "accuracy",
    "precision_potable",
    "recall_potable",
    "f1_potable",
    "f1_macro",
    "roc_auc",
    "confusion_matrix",
    "test_rows",
}


@pytest.fixture(scope="module")
def raw_dataset():
    pipeline.ensure_dataset()
    return pipeline.load_dataset()


@pytest.fixture(scope="module")
def trained():
    """Train once for the whole module (deterministic: seed=42)."""
    return pipeline.train()


def _artifact_from(trained_result):
    return {
        "model": trained_result["model"],
        "feature_columns": list(pipeline.FEATURE_COLUMNS),
        "labels": dict(pipeline.LABELS),
        "random_seed": trained_result["seed"],
        "metrics": trained_result["metrics"],
        "temperature_used": False,
    }


# ---------------------------------------------------------------- dataset ----
def test_dataset_loading(raw_dataset):
    """1. Dataset loads, checksum verified, expected size."""
    assert pipeline.DATASET_PATH.exists()
    assert pipeline.sha256_of(pipeline.DATASET_PATH) == pipeline.DATASET_SHA256
    assert raw_dataset.shape == (3276, 10)
    for column in pipeline.REQUIRED_RAW_COLUMNS:
        assert column in raw_dataset.columns


def test_dataset_validation(raw_dataset):
    """2. Dataset sanity: target domain, physical ranges, documented missing counts."""
    assert set(raw_dataset["Potability"].unique().tolist()) <= {0, 1}
    assert int(raw_dataset["ph"].isna().sum()) == 491
    assert int(raw_dataset["Solids"].isna().sum()) == 0
    assert int(raw_dataset["Turbidity"].isna().sum()) == 0
    assert int(raw_dataset.duplicated().sum()) == 0

    complete = raw_dataset.dropna(subset=["ph", "Solids", "Turbidity"])
    assert complete["ph"].between(0.0, 14.0).all()
    assert (complete["Solids"] >= 0.0).all()
    assert (complete["Turbidity"] >= 0.0).all()
    assert len(complete) == 2785


def test_feature_columns(raw_dataset):
    """3. Features are exactly the sensor-aligned columns (no temperature invention)."""
    assert pipeline.FEATURE_COLUMNS == ["ph", "tds", "turbidity"]
    assert pipeline.SOURCE_TO_FEATURE == {"ph": "ph", "Solids": "tds", "Turbidity": "turbidity"}
    assert "temperature" not in pipeline.FEATURE_COLUMNS

    clean, report = pipeline.preprocess(raw_dataset)
    assert list(clean.columns) == ["ph", "tds", "turbidity", "target"]
    assert report["temperature_used"] is False
    assert report["modelled_rows"] == 2785
    # only documented columns are dropped as unusable for our sensor set
    assert set(report["unused_dataset_columns"]) == {
        "Hardness",
        "Chloramines",
        "Sulfate",
        "Conductivity",
        "Organic_carbon",
        "Trihalomethanes",
    }


def test_target_encoding(raw_dataset):
    """4. Target stays binary and maps to the required output labels."""
    assert pipeline.TARGET_COLUMN == "Potability"
    assert pipeline.LABELS == {0: "NOT POTABLE", 1: "POTABLE"}
    clean, _report = pipeline.preprocess(raw_dataset)
    assert clean["target"].dtype.kind == "i"
    assert set(clean["target"].unique()) == {0, 1}
    assert clean["target"].value_counts().to_dict() == {0: 1684, 1: 1101}


# ---------------------------------------------------------------- model ------
def test_model_training(trained):
    """5. Model trains, is a fitted Random Forest, and reports full metrics."""
    from sklearn.ensemble import RandomForestClassifier

    assert isinstance(trained["model"], RandomForestClassifier)
    assert hasattr(trained["model"], "predict")
    assert list(trained["model"].feature_names_in_) == pipeline.FEATURE_COLUMNS

    assert REQUIRED_METRIC_KEYS <= set(trained["metrics"])
    assert 0.0 <= trained["metrics"]["accuracy"] <= 1.0
    assert 0.0 <= trained["metrics"]["roc_auc"] <= 1.0
    matrix = trained["metrics"]["confusion_matrix"]
    assert sum(matrix.values()) == trained["metrics"]["test_rows"]
    assert trained["metrics"]["test_rows"] == 557

    assert trained["selected_params"] in pipeline.CANDIDATE_MODELS
    assert trained["report"]["class_counts"] == {0: 1684, 1: 1101}


def test_train_test_independence(trained):
    """Test split is independent of the training split (no leakage by index)."""
    split = trained["split"]
    assert set(split["train_indices"]).isdisjoint(split["test_indices"])
    assert len(split["train_indices"]) + len(split["test_indices"]) == 2785
    # stratification preserved class proportions in both splits
    train_ratio = split["y_train"].mean()
    test_ratio = split["y_test"].mean()
    assert abs(train_ratio - test_ratio) < 0.02


def test_model_saving(trained, tmp_path):
    """6. Artifacts can be written to disk."""
    payload = _artifact_from(trained)
    path = pipeline.save_artifacts(payload, tmp_path / "model.joblib")
    assert path.exists()
    assert path.stat().st_size > 0


def test_model_loading(trained, tmp_path):
    """7. Saved artifact loads and reproduces the in-memory prediction."""
    payload = _artifact_from(trained)
    path = pipeline.save_artifacts(payload, tmp_path / "model.joblib")

    loaded = pipeline.load_artifacts(path)
    from_memory = pipeline.predict_record(payload, SAMPLE_RECORD)
    from_disk = pipeline.predict_record(loaded, SAMPLE_RECORD)
    assert from_disk == from_memory
    assert list(loaded["model"].feature_names_in_) == pipeline.FEATURE_COLUMNS


def test_prediction_output(trained):
    """8. Prediction label is one of the two allowed output strings."""
    payload = _artifact_from(trained)
    result = pipeline.predict_record(payload, SAMPLE_RECORD)
    assert result["prediction"] in {"POTABLE", "NOT POTABLE"}
    assert set(result["probabilities"]) == {"POTABLE", "NOT POTABLE"}


def test_probability_and_confidence_range(trained):
    """9. Probabilities/confidence are within [0, 1] and sum to 1."""
    payload = _artifact_from(trained)
    for record in [SAMPLE_RECORD] + EXTREME_RECORDS:
        result = pipeline.predict_record(payload, record)
        assert 0.0 <= result["confidence"] <= 1.0
        for value in result["probabilities"].values():
            assert 0.0 <= value <= 1.0
        total = sum(result["probabilities"].values())
        assert abs(total - 1.0) < 1e-6
        assert result["confidence"] == max(result["probabilities"].values())


def test_predict_cli_json_roundtrip(trained, capsys):
    """CLI accepts a JSON record and prints a valid classification."""
    exit_code = predict.main(["--json", json.dumps(SAMPLE_RECORD)])
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["prediction"] in {"POTABLE", "NOT POTABLE"}
    assert 0.0 <= payload["confidence"] <= 1.0
    assert payload["temperature_used"] is False


def test_invalid_inputs_rejected():
    """Invalid/missing sensor values are rejected instead of being imputed."""
    with pytest.raises(ValueError):
        pipeline.validate_record({"ph": 7.0, "tds": -5.0, "turbidity": 1.0})
    with pytest.raises(ValueError):
        pipeline.validate_record({"ph": 15.0, "tds": 100.0, "turbidity": 1.0})
    with pytest.raises(ValueError):
        pipeline.validate_record({"ph": None, "tds": 100.0, "turbidity": 1.0})
    with pytest.raises(ValueError):
        pipeline.validate_record({"ph": 7.0, "tds": 100.0})


def test_reproducibility(trained, raw_dataset):
    """10. Same seed + same data => identical metrics and identical predictions."""
    again = pipeline.train(raw_dataset, seed=pipeline.RANDOM_SEED)
    assert again["metrics"] == trained["metrics"]
    assert again["selected_params"] == trained["selected_params"]

    first = pipeline.predict_record(_artifact_from(trained), SAMPLE_RECORD)
    second = pipeline.predict_record(_artifact_from(again), SAMPLE_RECORD)
    assert first == second

    split_first = trained["split"]
    split_again = again["split"]
    assert split_first["train_indices"] == split_again["train_indices"]
    assert split_first["test_indices"] == split_again["test_indices"]


# ------------------------------------------------- saved production model ----
@pytest.mark.skipif(
    not (ROOT / "ml" / "models" / "water_potability_model.joblib").exists(),
    reason="production model artifact not trained yet",
)
def test_production_artifact_and_evaluate_script():
    """The committed artifact loads and the independent evaluator passes."""
    payload = pipeline.load_artifacts()
    assert payload["feature_columns"] == pipeline.FEATURE_COLUMNS
    assert payload["temperature_used"] is False
    result = pipeline.predict_record(payload, SAMPLE_RECORD)
    assert result["prediction"] in {"POTABLE", "NOT POTABLE"}

    completed = subprocess.run(
        [sys.executable, str(ROOT / "ml" / "evaluate.py")],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Metrics reproducible: OK" in completed.stdout
    assert "Train/test overlap: 0" in completed.stdout
