"""
Phase 4D/4F - Train the Random Forest water potability model and save it.

Usage:
    python ml/train.py

Steps:
    1. Download the labelled dataset if it is missing (SHA-256 verified).
    2. Preprocess deterministically (no fabricated values, fixed seed).
    3. Stratified train/test split (80/20, seed=42).
    4. Fit a Random Forest classifier on the training split only.
    5. Evaluate on the held-out test split.
    6. Persist model + metadata to ml/models/water_potability_model.joblib.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sklearn  # noqa: E402

from ml import pipeline  # noqa: E402


def main() -> int:
    print("=" * 70)
    print("Phase 4 - Water Potability Random Forest training")
    print("=" * 70)

    path = pipeline.ensure_dataset()
    print(f"Dataset          : {path}")
    print(f"SHA-256          : {pipeline.sha256_of(path)}")
    print(f"Source           : {pipeline.DATASET_KAGGLE_URL}")

    raw = pipeline.load_dataset(path)
    print(f"Raw rows/columns : {raw.shape[0]} rows x {raw.shape[1]} columns")
    print(f"Raw missing      : {raw.isna().sum().to_dict()}")

    result = pipeline.train(raw, seed=pipeline.RANDOM_SEED, path=path)
    report = result["report"]
    metrics = result["metrics"]
    split = result["split"]

    print("-" * 70)
    print("Preprocessing report")
    for key, value in report.items():
        print(f"  {key:30s}: {value}")

    total = report["modelled_rows"]
    counts = report["class_counts"]
    print("-" * 70)
    print("Class distribution (after cleaning)")
    for label, count in sorted(counts.items()):
        print(f"  {pipeline.LABELS[label]:12s}: {count:>5d} ({100.0 * count / total:.2f}%)")
    majority = max(counts.values()) / total
    minority = min(counts.values()) / total
    print(f"  imbalance ratio (majority:minority) = {majority / minority:.2f}:1")

    print("-" * 70)
    print(
        f"Split: {len(split['train_indices'])} train / {len(split['test_indices'])} test "
        f"(stratified, test_size={pipeline.TEST_SIZE}, seed={pipeline.RANDOM_SEED})"
    )
    print(
        "Independent test set: "
        f"{'OK - no index overlap' if not set(split['train_indices']) & set(split['test_indices']) else 'FAILED'}"
    )
    print(f"Features          : {pipeline.FEATURE_COLUMNS} (temperature not available in dataset)")
    print("-" * 70)
    print("Hyper-parameter selection: 5-fold CV ROC-AUC on the TRAINING split only")
    for trial in result["selection_trials"]:
        marker = "  <- selected" if trial["params"] == result["selected_params"] else ""
        print(
            f"  {trial['params']}  AUC={trial['cv_roc_auc_mean']:.4f}"
            f"+/-{trial['cv_roc_auc_std']:.4f}{marker}"
        )
    print(
        f"Model             : RandomForest({result['selected_params']}, "
        f"random_state={pipeline.RANDOM_SEED}, n_jobs=1)"
    )
    print("-" * 70)
    print("Test-set metrics")
    print(pipeline.format_metrics(metrics))
    print("-" * 70)
    print("Feature importances")
    for column, value in sorted(
        result["feature_importances"].items(), key=lambda item: item[1], reverse=True
    ):
        print(f"  {column:12s}: {value:.4f}")

    payload = {
        "model": result["model"],
        "feature_columns": list(pipeline.FEATURE_COLUMNS),
        "labels": dict(pipeline.LABELS),
        "random_seed": pipeline.RANDOM_SEED,
        "test_size": pipeline.TEST_SIZE,
        "model_params": result["selected_params"],
        "selection_trials": result["selection_trials"],
        "train_indices": split["train_indices"],
        "test_indices": split["test_indices"],
        "preprocessing_report": report,
        "metrics": metrics,
        "feature_importances": result["feature_importances"],
        "dataset": {
            "name": pipeline.DATASET_NAME,
            "kaggle_url": pipeline.DATASET_KAGGLE_URL,
            "mirror_url": pipeline.DATASET_MIRROR_URL,
            "sha256": pipeline.DATASET_SHA256,
            "raw_rows": int(raw.shape[0]),
            "modelled_rows": int(total),
        },
        "temperature_used": False,
        "sklearn_version": sklearn.__version__,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    saved = pipeline.save_artifacts(payload)
    metrics_path = pipeline.MODEL_DIR / "model_metrics.json"
    metrics_payload = {
        "dataset": payload["dataset"],
        "feature_columns": payload["feature_columns"],
        "temperature_used": False,
        "preprocessing_report": report,
        "split": {
            "train_rows": len(split["train_indices"]),
            "test_rows": len(split["test_indices"]),
            "stratified": True,
            "random_seed": pipeline.RANDOM_SEED,
            "test_size": pipeline.TEST_SIZE,
        },
        "model": "RandomForestClassifier",
        "model_params": result["selected_params"],
        "selection_trials": result["selection_trials"],
        "test_metrics": metrics,
        "feature_importances": result["feature_importances"],
        "majority_baseline_accuracy": round(
            max(counts.values()) / total, 4
        ),
        "trained_at": payload["trained_at"],
        "disclaimer": "Prototype model - not a guarantee of drinking-water safety.",
    }
    metrics_path.write_text(pipeline.dump_json(metrics_payload), encoding="utf-8")
    print("-" * 70)
    print(f"Model saved       : {saved} ({saved.stat().st_size} bytes)")
    print(f"Metrics saved     : {metrics_path}")
    print("Note              : prototype model - not a guarantee of drinking-water safety.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
