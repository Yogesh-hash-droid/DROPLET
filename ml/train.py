"""
Phase 5 v2 - Train the water potability ML model and save it.

Dataset selection logic:
  1. Try to download and verify the Kaggle Water Potability dataset.
     If successful, train on it (ROC-AUC ~0.55-0.58 with 3 features — documented limit).
  2. If download fails OR --simulated flag is set, generate a SIMULATED dataset
     based on WHO/BIS thresholds with realistic noise (ROC-AUC ~0.97+).
     ⚠️ LEAKAGE: labels come from the same rules as the features.
     This is documented on the dashboard as "SIMULATED / THRESHOLD-DERIVED".

Usage:
    python ml/train.py                    # Kaggle dataset (honest but ~61% acc)
    python ml/train.py --simulated        # Simulated WHO dataset (90%+ acc, labeled as SIMULATED)
    python ml/train.py --simulated --n 10000  # Larger simulated set
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sklearn  # noqa: E402

from ml import pipeline  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="Train the DROPLET water quality ML model")
    p.add_argument("--simulated", action="store_true",
                   help="Use simulated WHO-threshold dataset (labels 90%+ accuracy, but labeled as SIMULATED)")
    p.add_argument("--n", type=int, default=pipeline.SIMULATED_N,
                   help="Number of simulated samples (only with --simulated)")
    return p.parse_args()


def main(args=None) -> int:
    if args is None:
        args = parse_args()

    use_simulated = args.simulated

    print("=" * 70)
    print("Phase 5 v2 - Water Quality ML Model Training")
    print("=" * 70)

    # --- Load / generate dataset ---
    raw, source_label, is_simulated = pipeline.generate_or_load_dataset(
        use_simulated=use_simulated, seed=pipeline.RANDOM_SEED
    )

    if is_simulated:
        print(f"Dataset          : SIMULATED (WHO/BIS threshold-derived, N={len(raw)})")
        print("[!] LEAKAGE WARNING: labels derived from same thresholds used as features.")
        print("   High accuracy (~95-98%) is expected but reflects threshold learning, NOT")
        print("   generalisation to unseen sensor noise distributions.")
        print("   This is labeled 'SIMULATED' on the dashboard. It is advisory only.")
    else:
        path = pipeline.DATASET_PATH
        print(f"Dataset          : {path}")
        print(f"SHA-256          : {pipeline.sha256_of(path)}")
        print(f"Source           : {pipeline.DATASET_KAGGLE_URL}")

    print(f"Raw rows/columns : {raw.shape[0]} rows x {raw.shape[1]} columns")
    if not is_simulated:
        print(f"Raw missing      : {raw.isna().sum().to_dict()}")

    result = pipeline.train(raw, seed=pipeline.RANDOM_SEED, is_simulated=is_simulated)
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
    print(f"Features          : {pipeline.FEATURE_COLUMNS} (temperature not used)")
    print("-" * 70)
    print("Hyper-parameter selection: 5-fold CV ROC-AUC on the TRAINING split only")
    print("Candidates: RandomForest, GradientBoosting, LogisticRegression")
    for trial in result["selection_trials"]:
        marker = "  <- SELECTED" if trial["params"] == {k: v for k, v in result["selected_params"].items() if k != "model_type"} and trial["model_type"] == result["selected_params"].get("model_type") else ""
        print(
            f"  [{trial['model_type']:20s}] {trial['params']}  AUC={trial['cv_roc_auc_mean']:.4f}"
            f"+/-{trial['cv_roc_auc_std']:.4f}{marker}"
        )
    print(f"Selected model    : {result['selected_params']}")
    print("-" * 70)
    print("Test-set metrics (honest, test set never used for selection)")
    print(pipeline.format_metrics(metrics))
    if metrics["accuracy"] >= 0.90:
        print(f"[OK] Accuracy {metrics['accuracy']:.1%} meets 90% target")
    else:
        print(f"[!] Accuracy {metrics['accuracy']:.1%} is below 90% target")
        if not is_simulated:
            print("   Consider running with --simulated to use the WHO-threshold dataset.")
    print("-" * 70)
    print("Feature importances")
    for column, value in sorted(
        result["feature_importances"].items(), key=lambda item: item[1], reverse=True
    ):
        print(f"  {column:12s}: {value:.4f}")

    trained_at = datetime.now(timezone.utc).isoformat()
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
            "name": f"{pipeline.DATASET_NAME} ({'SIMULATED' if is_simulated else 'Kaggle'})",
            "kaggle_url": pipeline.DATASET_KAGGLE_URL if not is_simulated else None,
            "simulated": is_simulated,
            "raw_rows": int(raw.shape[0]),
            "modelled_rows": int(total),
            "leakage_warning": (
                "Labels derived from WHO/BIS threshold rules used as features. "
                "High accuracy reflects threshold learning, not real-world generalisation."
            ) if is_simulated else None,
        },
        "temperature_used": False,
        "sklearn_version": sklearn.__version__,
        "trained_at": trained_at,
        "is_simulated": is_simulated,
    }
    saved = pipeline.save_artifacts(payload)

    metrics_path = pipeline.MODEL_DIR / "model_metrics.json"
    metrics_payload = {
        "dataset": payload["dataset"],
        "feature_columns": payload["feature_columns"],
        "temperature_used": False,
        "is_simulated": is_simulated,
        "leakage_warning": payload["dataset"].get("leakage_warning"),
        "preprocessing_report": report,
        "split": {
            "train_rows": len(split["train_indices"]),
            "test_rows": len(split["test_indices"]),
            "stratified": True,
            "random_seed": pipeline.RANDOM_SEED,
            "test_size": pipeline.TEST_SIZE,
        },
        "model": result["selected_params"].get("model_type", "RandomForestClassifier"),
        "model_params": result["selected_params"],
        "selection_trials": result["selection_trials"],
        "test_metrics": metrics,
        "feature_importances": result["feature_importances"],
        "majority_baseline_accuracy": round(max(counts.values()) / total, 4),
        "trained_at": trained_at,
        "disclaimer": (
            "SIMULATED dataset (WHO/BIS threshold-derived). "
            "Labels come from the same rules as features — high accuracy reflects "
            "threshold learning. Advisory only, never a guarantee of water safety."
            if is_simulated else
            "Kaggle dataset prototype — not a guarantee of drinking-water safety."
        ),
    }
    metrics_path.write_text(pipeline.dump_json(metrics_payload), encoding="utf-8")
    print("-" * 70)
    print(f"Model saved       : {saved} ({saved.stat().st_size} bytes)")
    print(f"Metrics saved     : {metrics_path}")
    if is_simulated:
        print("[DISCLAIMER] SIMULATED data -- labels derived from WHO thresholds.")
        print("   Dashboard will show 'SIMULATED' clearly. Never present as real lab data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
