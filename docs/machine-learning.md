# Phase 4 — ML Model Report (Water Potability)

> Companion to `ml/README.md` (dataset card). This document records what was
> trained, how it was validated, what the numbers actually mean, and how the
> model is served by the API since **Phase 5**.

## 1. Objective

Predict `POTABLE` / `NOT POTABLE` from the project's sensor readings, using a
Random Forest classifier, without ever contradicting or replacing the
deterministic Safety Rule Engine.

## 2. Pipeline (all steps deterministic, seed = 42)

1. **Acquire** — `ml/data/water_potability.csv`, SHA-256 verified on every run.
2. **Preprocess (subtractive only)** — map `ph→ph`, `Solids→tds`,
   `Turbidity→turbidity`; coerce to numeric; drop rows outside physical ranges
   (ph 0–14, tds ≥ 0, turbidity ≥ 0); drop rows with missing feature/target
   values; drop duplicates; drop feature-identical rows with conflicting
   labels; encode target as `0/1`. **No value is imputed, simulated or invented.**
3. **Split** — stratified 80/20 → **2 228 train / 557 test**, `random_state=42`.
   The test set is used once, after model selection.
4. **Model selection** — 5-fold stratified CV **on the training split only**,
   ranked by ROC-AUC (not accuracy):

   | Candidate | CV ROC-AUC |
   | --- | --- |
   | depth=None, leaf=1 | 0.5637 ± 0.0071 |
   | depth=8, leaf=1 | 0.5725 ± 0.0130 |
   | **depth=8, leaf=5 (selected)** | **0.5795 ± 0.0167** |
   | depth=12, leaf=3 | 0.5720 ± 0.0122 |

5. **Fit** — `RandomForestClassifier(n_estimators=200, max_depth=8,
   min_samples_leaf=5, random_state=42, n_jobs=1)`.
   `class_weight` deliberately left default: the majority class is
   `NOT POTABLE`, so the un-weighted model errs towards "do not declare
   potable", which is the safe direction.

## 3. Held-out test results (557 samples)

| Metric | Value |
| --- | --- |
| Accuracy | **0.6104** (majority baseline 0.6050) |
| Precision (POTABLE) | **0.5429** |
| Recall (POTABLE) | **0.0864** |
| F1 (POTABLE) | **0.1490** |
| F1 (macro) | **0.4482** |
| ROC-AUC | **0.5522** |
| Confusion matrix | TN = 321, FP = 16, FN = 201, TP = 19 |
| Feature importance | ph 0.3522 · tds 0.3450 · turbidity 0.3028 |

Confusion matrix rows = actual, columns = predicted, order `[NOT POTABLE, POTABLE]`.

### Error analysis for a water-safety system

Two ways to read the same matrix, both stated explicitly:

- **With `POTABLE` as the positive class** — `FP = 16` samples were predicted
  POTABLE but were actually NOT POTABLE: **false reassurance**, the dangerous
  error. `FN = 201` were actually POTABLE but predicted NOT POTABLE:
  conservative, safe but inconvenient.
- **With `NOT POTABLE` as the positive class (unsafe detection)** — the same
  `FP = 16` are the "false negatives": unsafe water that the model failed to
  flag. **This is the error that matters for health**, and it is exactly the
  error class a high recall/accuracy figure can hide.

Because precision for `POTABLE` is 0.543, roughly **46 % of samples the model
calls POTABLE are not potable**. Combined with a test accuracy that is only
0.5 percentage points above the trivial baseline and a ROC-AUC of 0.552, the
model has weak discriminative power and **must not be used to certify water**.
Reporting these numbers is intentional — fabricating stronger metrics would be
scientifically dishonest.

Root cause (verified diagnostically, not deployed): single-feature ROC-AUC on
the test set is 0.517 (ph), 0.508 (tds), 0.537 (turbidity); the three features
have ≈0 correlation with the target. A diagnostic model using all nine raw
columns reaches CV ROC-AUC ≈ 0.706, so the signal exists mainly in columns our
hardware cannot measure (sulfate, chloramines, trihalomethanes, conductivity,
hardness, organic carbon) — using them would break sensor consistency.

## 4. Validation checklist (Phase 4E)

| Check | Result |
| --- | --- |
| Test set independent of training set | ✅ 0 index overlap (2 228 + 557 = 2 785) |
| No target leakage | ✅ selection uses training split only; no target-derived features |
| Preprocessing reproducible | ✅ deterministic, seed 42, dataset SHA-256 verified |
| Prediction labels | ✅ only `POTABLE` / `NOT POTABLE` |
| Probabilities in [0, 1] | ✅ per class, summing to 1; confidence = max class probability |
| Model loads after saving | ✅ `ml/evaluate.py` reloads the artifact |
| Inference on sample records | ✅ `ml/predict.py` normal + extreme + invalid inputs |
| Metrics reproducible after reload | ✅ byte-identical metrics vs training time |
| Invalid inputs rejected | ✅ null / out-of-range values raise `ValueError` (never imputed) |

## 5. Reproducing

```bash
python ml/train.py       # train + save artifacts
python ml/evaluate.py    # independent verification
python ml/predict.py --ph 7.2 --tds 250 --turbidity 1.5
cd backend && python -m pytest -q
```

## 6. Phase 5 — API integration (EXPERIMENTAL / ADVISORY)

The trained artifact is now served by the FastAPI backend:

| Aspect | Implementation |
| --- | --- |
| Service | `backend/app/ml/service.py` — `MLInferenceService` (lazy, thread-safe, one artifact per process; warmed up at startup) |
| Artifact | `ml/models/water_potability_model.joblib` via `settings.MODEL_PATH` (no retraining, no model change) |
| Inputs | exactly `ph`, `tds`, `turbidity` (from the stored reading); **temperature is never passed** |
| Output | `prediction` ∈ {`POTABLE`, `NOT POTABLE`} + `confidence` = probability of that class ∈ `[0, 1]` |
| Storage | existing `predictions` table (`prediction`, `confidence` columns) — no new tables |
| Endpoint | `GET /api/predictions/latest` (404 when no stored verdict) |
| Failure mode | load/inference errors → logged, `prediction = NULL`, `confidence = NULL`; safety evaluation and score still run |
| Independence | `safety_status` / `quality_score` come only from the rule engine; a `POTABLE` verdict never downgrades an `UNSAFE` status |

Observed behaviour (live API): the two engines genuinely disagree — e.g.
`ph 5.5` → `safety_status: UNSAFE` with `prediction: POTABLE`; `temperature 60 °C`
→ `UNSAFE` (temperature is invisible to the model) with `prediction: POTABLE`;
`ph 7.4 / tds 480 / turbidity 4.5` → `SAFE` with `prediction: NOT POTABLE`.

## 7. Status

- Phase 4 deliverables (dataset documentation, preprocessing, training,
  evaluation, persistence, tests) are **complete**.
- Phase 5 (ML API integration: `prediction`/`confidence` in
  `POST /api/readings`, persistence, `GET /api/predictions/latest`) is
  **complete** — verified with the live server and MySQL.
- The model is presented everywhere as an *experimental, advisory* signal that
  can never override the Safety Rule Engine; it does not make water safe.

## 8. Phase 11 — hardware-mode ML compatibility

The final hardware target is an **ESP8266 NodeMCU with an ADS1115 ADC,
TDS sensor and turbidity sensor**. In this mode:

- TDS and turbidity are measured.
- pH and temperature are not measured.
- Missing pH remains `NULL` throughout validation, persistence and API
  responses.
- pH is never synthesized, defaulted, imputed or inferred from another sensor.

The existing three-feature artifact requires `ph`, `tds` and `turbidity`.
Therefore, when pH is unavailable, the backend skips ML inference and stores
an explicit unavailable result:

```text
prediction = NULL
confidence = NULL
ml_status = UNAVAILABLE
ml_status_reason = PH_NOT_MEASURED
```

The deterministic TDS/turbidity rule evaluation and the two-parameter Water
Quality screening score continue normally. An unavailable ML result never means
`NOT POTABLE`, and the Safety Rule Engine remains authoritative.

This compatibility behavior does not change legacy processing. Readings that
contain pH continue through the existing three-feature inference path using
the unchanged `ml/models/water_potability_model.joblib` artifact. Required
Phase 11 work does not include retraining a two-feature model; any such
experiment requires separate evaluation and approval.

The Phase 11 application behavior is substantially implemented. Formal
acceptance remains blocked by the documented Phase 10 gates: production
migration is **NOT APPROVED**, Gate 4 regression/integration acceptance is
pending, and Gate 5 Phase 11 approval is pending. No production deployment is
authorized by this document.
