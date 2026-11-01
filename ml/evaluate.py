"""
Phase 4E - Independently evaluate the saved model.

Usage:
    python ml/evaluate.py

Verifies:
    1. The artifact loads successfully.
    2. The stored train/test index split is reproducible from the dataset.
    3. The test split is independent (no overlap with the training split).
    4. Recomputed metrics exactly match the metrics stored at training time.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import pipeline  # noqa: E402


def main() -> int:
    print("=" * 70)
    print("Phase 4 - Independent model evaluation")
    print("=" * 70)

    payload = pipeline.load_artifacts()
    model = payload["model"]
    print(f"Model artifact    : {pipeline.MODEL_PATH}")
    print(f"Trained at        : {payload.get('trained_at')}")
    print(f"scikit-learn      : {payload.get('sklearn_version')} (runtime {__import__('sklearn').__version__})")
    print(f"Features          : {payload['feature_columns']}")

    is_simulated = payload.get("is_simulated", False)
    if is_simulated:
        raw = pipeline.generate_simulated_dataset(seed=payload.get("random_seed", pipeline.RANDOM_SEED))
        clean, _report = pipeline.preprocess(raw, is_simulated=True)
    else:
        raw = pipeline.load_dataset()
        clean, _report = pipeline.preprocess(raw, is_simulated=False)
    split = pipeline.split_data(clean, seed=payload.get("random_seed", pipeline.RANDOM_SEED))

    train_set = set(split["train_indices"])
    test_set = set(split["test_indices"])
    overlap = train_set & test_set
    print(f"Split rows        : {len(train_set)} train / {len(test_set)} test")
    print(f"Train/test overlap: {len(overlap)} {'(independent - OK)' if not overlap else 'LEAKAGE!'}")
    if overlap:
        print("FAILED: test set is not independent of the training set.")
        return 1

    if split["train_indices"] != payload.get("train_indices") or split["test_indices"] != payload.get(
        "test_indices"
    ):
        print("FAILED: stored split is not reproducible from the dataset + seed.")
        return 1
    print("Split reproducible: OK (identical indices regenerated from dataset + seed)")

    metrics = pipeline.compute_metrics(model, split["X_test"], split["y_test"])
    stored = payload["metrics"]
    mismatches = []
    for key, value in stored.items():
        if isinstance(value, float):
            if abs(value - metrics[key]) > 1e-12:
                mismatches.append(key)
        elif value != metrics[key]:
            mismatches.append(key)
    if mismatches:
        print(f"FAILED: metric mismatch vs training time: {mismatches}")
        return 1
    print("Metrics reproducible: OK (identical to training-time metrics)")

    print("-" * 70)
    print("Held-out test set metrics")
    print(pipeline.format_metrics(metrics))
    print("-" * 70)
    print("Interpretation for water safety:")
    matrix = metrics["confusion_matrix"]
    print(f"  FP={matrix['fp']} -> predicted POTABLE but actually NOT POTABLE "
          "(critical error: false reassurance)")
    print(f"  FN={matrix['fn']} -> predicted NOT POTABLE but actually POTABLE "
          "(conservative: safe but inconvenient)")
    print("Prototype output only - does not certify drinking-water safety.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
