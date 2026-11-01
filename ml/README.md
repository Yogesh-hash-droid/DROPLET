# Machine Learning — Water Potability Prediction (Phase 4)

Random Forest classifier that predicts **POTABLE / NOT POTABLE** from the same
sensor values the hardware will measure. The dataset, preprocessing, training,
evaluation and model persistence belong to Phase 4; since **Phase 5** the
saved artifact is served by the FastAPI backend (`backend/app/ml/service.py`,
`GET /api/predictions/latest`) as an **EXPERIMENTAL / ADVISORY** verdict.

> **Disclaimer**: this is an educational prototype. It does **not** certify that
> water is safe to drink. The deterministic Safety Rule Engine (Phase 3) stays
> the authority for safety decisions and remains completely independent.

---

## 1. Dataset documentation (Phase 4B)

| Field | Value |
| --- | --- |
| Dataset name | **Water Potability** |
| Source | Kaggle dataset *Water Quality / Drinking water potability* by Aditya Kadiwal |
| Source URL (canonical) | https://www.kaggle.com/datasets/adityakadiwal/water-potability |
| Mirror used for download | https://raw.githubusercontent.com/Sarthak-1408/Water-Potability/main/water_potability.csv |
| Local file | `ml/data/water_potability.csv` |
| SHA-256 | `904004bde729bfe3d2e195f46343bceead09e32a0eb95bb8184e7e20e029b2bf` (verified by `ml/pipeline.py` on every run) |
| Rows | **3 276** water samples |
| Columns | **10** (9 features + 1 target) |
| Target column | `Potability` — `1` = potable, `0` = not potable |
| Class distribution (raw) | `0` = 1 998 (60.99 %), `1` = 1 278 (39.01 %) → imbalance **1.56 : 1** |
| Missing values | `ph` 491 · `Sulfate` 781 · `Trihalomethanes` 162 · all other columns 0 |
| Duplicate rows | **0** (full-row); 0 conflicting labels inside the selected feature subset |
| Licence / provenance | Publicly redistributed Kaggle educational dataset; per-sample laboratory metadata is **not** published (see Limitations) |

### 1.1 All raw columns, units and meaning

| Dataset column | Unit | Meaning | Used? |
| --- | --- | --- | --- |
| `ph` | pH units (0–14) | Acidity/alkalinity of the water | ✅ feature `ph` |
| `Hardness` | mg/L | Calcium/magnesium concentration | ❌ no sensor on our device |
| `Solids` | ppm (= mg/L) | **Total Dissolved Solids (TDS)** | ✅ feature `tds` |
| `Chloramines` | ppm | Disinfectant residual | ❌ no sensor |
| `Sulfate` | mg/L | Sulfate concentration | ❌ no sensor |
| `Conductivity` | µS/cm | Electrical conductivity | ❌ no sensor |
| `Organic_carbon` | ppm | Organic carbon | ❌ no sensor |
| `Trihalomethanes` | µg/L | Disinfection by-products | ❌ no sensor |
| `Turbidity` | NTU | Water cloudiness / suspended particles | ✅ feature `turbidity` |
| `Potability` | 0 / 1 | Label: safe for consumption | ✅ target |

**No column is renamed to pretend it is something else**: `Solids` is mapped to
`tds` because it *is* the dataset's Total Dissolved Solids measurement in ppm —
the same physical quantity as our TDS sensor output. Every other unmapped
column is documented above and excluded rather than repurposed.

### 1.2 Selected features and why they match the sensor architecture

| Project feature | Sensor on the ESP32 build | Dataset column | Unit | Rationale |
| --- | --- | --- | --- | --- |
| `ph` | Analog pH probe | `ph` | pH | Direct 1:1 match with sensor output |
| `tds` | TDS sensor | `Solids` | ppm | `Solids` is defined as total dissolved solids — the exact quantity a TDS sensor reports |
| `turbidity` | Turbidity sensor | `Turbidity` | NTU | Direct 1:1 match with sensor output |
| **(temperature)** | DS18B20 temperature probe | **not present** | °C | **The labelled dataset contains no temperature column.** Temperature is therefore **excluded from ML** — no value is invented, simulated or copied. It is still used by the Phase 3 Safety Rule Engine. |

### 1.3 Rows kept for modelling

Cleaning is *subtractive only* (rows are removed, never invented):

- 491 rows with a missing `ph` are dropped → **2 785 rows** remain
  (`Solids` and `Turbidity` have no missing values).
- 0 rows outside physical ranges, 0 duplicates, 0 conflicting labels.
- Final class balance: `NOT POTABLE` 1 684 (60.47 %) vs `POTABLE` 1 101 (39.53 %) → imbalance **1.53 : 1**.

---

## 2. Scripts

| Script | Purpose |
| --- | --- |
| `ml/train.py` | Download (SHA-256 verified) → preprocess → stratified split → 5-fold CV model selection on the **training split only** → fit → evaluate on the held-out test split → save `models/water_potability_model.joblib` + `models/model_metrics.json` |
| `ml/evaluate.py` | Reloads the artifact, regenerates the split from dataset + seed, verifies train/test independence and that metrics are identical to training time |
| `ml/predict.py` | Single-record inference: `python ml/predict.py --ph 7.2 --tds 250 --turbidity 1.5` or `--json '{"ph":7.2,"tds":250,"turbidity":1.5}'` |
| `ml/pipeline.py` | Shared configuration, preprocessing, training, metrics and persistence helpers |

Run from the repository root or `backend/`:

```bash
python ml/train.py
python ml/evaluate.py
python ml/predict.py --ph 7.2 --tds 250 --turbidity 1.5
```

Configuration (paths, seed, feature list, model grid) lives in `ml/pipeline.py`.
The API never re-trains: Phase 5 loads the saved artifact from
`ml/models/` (see `backend/app/ml/service.py`).

## 3. Artifacts

- `ml/models/water_potability_model.joblib` — model + feature list + label map + split indices + metrics (≈ 1.9 MB)
- `ml/models/model_metrics.json` — human/machine-readable metrics report
- `ml/data/water_potability.csv` — raw dataset (513 KB, checksum-verified)

## 4. Tests

`backend/tests/test_ml_pipeline.py` covers dataset loading, dataset validation,
feature columns, target encoding, model training, saving, loading, prediction
output, probability/confidence ranges, invalid-input rejection, train/test
independence, reproducibility and the independent evaluator.
`backend/tests/test_phase5_ml_api.py` covers the API integration: model
loading, inference, `POST /api/readings`, persistence,
`GET /api/predictions/latest`, safety/ML disagreement and ML failure handling.

```bash
cd backend && python -m pytest -q     # 119 tests (57 Phase 1-3 + 14 Phase 4 + 14 Phase 5 + 31 Phase 6 + 3 Phase 8)
```

## 5. Limitations (read before using any output)

1. **Temperature is not used by ML** — the labelled dataset has no temperature
   column. The ML verdict covers 3 of the 4 sensors.
2. **Weak predictive signal.** With only `ph`/`tds`/`turbidity`, single-feature
   ROC-AUC is 0.51–0.54 and the model reaches **ROC-AUC 0.552** on the held-out
   test set — only marginally better than chance. (A diagnostic model using all
   9 raw columns reaches ≈ 0.71, but 6 of those columns cannot be measured by
   our hardware, so they are not used.)
3. **Accuracy is only marginally above the majority baseline** (0.610 vs 0.605
   "always NOT POTABLE").
4. **`POTABLE` predictions are not trustworthy**: precision for `POTABLE` is
   0.543, i.e. ~46 % of samples labelled POTABLE were actually NOT POTABLE in
   the test set. The ML output must never be used to certify water.
5. **Provenance**: the Kaggle dataset does not publish sampling sites, dates or
   laboratory accreditation, and does not document the criteria used to assign
   the `Potability` label.
6. Single random stratified split — no temporal or geographic external
   validation; metrics may not transfer to our own sensors' readings.
7. Noisy consumer-grade sensor values differ from the dataset's analytical
   measurements.

**Consequence**: Phase 4 produces a working, reproducible, honestly evaluated
prototype. It does **not** justify presenting the system as an ML-certified
drinking-water checker; the rule engine remains the safety authority.
