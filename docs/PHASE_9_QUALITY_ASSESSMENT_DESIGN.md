# Phase 9 — Two-Parameter Water-Quality Assessment Design

> **Status:** DESIGN CORRECTED & DECISIONS FINALIZED (Phase 9 review round) — **still not implemented.** No scoring code, thresholds or configuration defaults were changed in any runtime file.
> **Scope:** revised Water Quality Score + **Parameter Rule Check** using **TDS and turbidity only**.
> **Finalized inputs:** weights **0.55 / 0.45** (D1), bands **GOOD ≥ 70 / POOR < 40** (D4), rule labels **PASS / WARNING / FAIL** (D8).
> **Related:** `docs/PHASE_9_MIGRATION_DESIGN.md` §6 · `docs/PHASE_9_DASHBOARD_SPECIFICATION.md` · `docs/api.md`

---

## 1. Safety Disclaimer (applies to everything below)

This is a **preliminary screening metric** for an educational prototype. It is **not** an official Water Quality Index (WQI), **not** a certification, and **must never be presented as proof that water is safe to drink**.

**TDS and turbidity alone cannot detect every harmful contaminant.** They do **not** measure bacteria, viruses, parasites, dissolved heavy metals, pesticides, nitrates, fluorides, or many other chemical pollutants — all of which can be dangerous at levels that leave TDS and turbidity looking normal. Water that scores **GOOD** — and water that shows **PASS** on both parameter checks — may still be unsafe.

**Laboratory testing of the water supply is required to confirm drinking-water safety.** No score or rule-check result produced by this system replaces a certified laboratory analysis.

---

## 2. What Changes

| Aspect | Legacy (4-parameter, historical rows) | Proposed (2-parameter, new rows) |
|---|---|---|
| Inputs | pH, TDS, Turbidity, Temperature | **TDS, Turbidity only** |
| Weights | 0.35 / 0.30 / 0.25 / 0.10 | **0.55 / 0.45** (finalized) |
| Rule output labels | `SAFE` / `WARNING` / `UNSAFE` (stored & displayed) | **Parameter Rule Check: `PASS` / `WARNING` / `FAIL`** (displayed) |
| Score status bands | frontend bands (Excellent/Good/Moderate/Poor/Critical) | **`GOOD` / `MODERATE` / `POOR` / `UNAVAILABLE`** |
| ML involvement | none | **none** — the 3-feature ML model never generates this score |

**Two separate outputs, never merged:**

1. **Preliminary Screening Score** — arithmetic 0–100 value from the two sub-indices (§5) + its `screening_status` band (§7).
2. **Parameter Rule Check** — deterministic per-parameter threshold verdicts for TDS and turbidity only (§6).

**Historical preservation:** rows written before the Phase 10 cutover keep their stored `safety_status` (`SAFE`/`WARNING`/`UNSAFE`) with its original **four-parameter meaning** and their four-parameter `quality_score` (`score_method` = `NULL`/`FOUR_PARAM_LEGACY`). Historical assessment records are never rewritten or relabelled. The `PASS`/`WARNING`/`FAIL` terminology applies to the **new two-sensor assessment display only**.

---

## 3. Proposed Sub-Indices (unchanged from the audit design)

Both sub-indices reuse the **existing implementation's curves** so the two retained parameters keep their familiar behaviour. Defaults: `tds_max = 500` ppm, `turbidity_max = 5.0` NTU.

### 3.1 `S_tds` — TDS sub-index (ppm)

| Range | Sub-index |
|---|---|
| `tds ≤ 200` | `100` |
| `200 < tds ≤ tds_max` | `S_tds = 100 − 20 × (tds − 200) / (tds_max − 200)` |
| `tds_max < tds ≤ max(tds_max + 100, 2000)` | `S_tds = 80 × (1 − (tds − tds_max) / (max(tds_max + 100, 2000) − tds_max))` |
| above that | `0` |

### 3.2 `S_turb` — Turbidity sub-index (NTU)

| Range | Sub-index |
|---|---|
| `turbidity ≤ 1.0` | `100` |
| `1.0 < turbidity ≤ turbidity_max` | `S_turb = 100 − 25 × (turbidity − 1.0) / (turbidity_max − 1.0)` |
| `turbidity_max < turbidity ≤ max(turbidity_max + 5, 50)` | `S_turb = 75 × (1 − (turbidity − turbidity_max) / (max(turbidity_max + 5, 50) − turbidity_max))` |
| above that | `0` |

Both sub-indices are clamped to `[0, 100]`.

---

## 4. Weights (FINALIZED — D1)

| Parameter | Weight | Contribution |
|---|---|---|
| **TDS** | **0.55 (55 %)** | `S_tds × 0.55` |
| **Turbidity** | **0.45 (45 %)** | `S_turb × 0.45` |
| **Total** | **1.00** | |

Rationale (retained): normalises the legacy relative importance of the two retained parameters (0.30 : 0.25 → 0.545 : 0.455, rounded to 0.55 / 0.45 so the total is exactly 1.00). These weights are now **frozen** — changing them later would create another score version.

---

## 5. Score Calculation (FINALIZED FORMULA)

```
quality_score = round( (S_tds × 0.55) + (S_turbidity × 0.45), 1 )     # clamped to [0.0, 100.0]
```

Rules:
- TDS contributes **55 %**, turbidity contributes **45 %**, range strictly **0–100**.
- Sub-indices are computed at full precision; **only the final score is rounded** (1 decimal place).
- **If either required input is missing or invalid → no score is calculated.** The result is `quality_score = null` with `screening_status = "UNAVAILABLE"`. **A partial one-parameter score is never produced**, and no value is defaulted, inferred or fabricated.
- Inputs rejected at the API boundary (`422`: negative, boolean, non-numeric, out of physical range) are never stored, so a stored reading with `null` TDS/turbidity is the only path to `UNAVAILABLE` (legacy rows may also be missing values after the migration).

### 5.1 Worked examples — manually verified against the formula

Defaults `tds_max = 500`, `turbidity_max = 5.0`. Intermediate sub-indices are shown at 2 decimals for auditability.

| # | TDS (ppm) | Turb. (NTU) | `S_tds` | `S_turb` | Calculation | **Score** | Status |
|---|---|---|---|---|---|---|---|
| 1 | 215 | 1.4 | 99.00 | 97.50 | 99.00×0.55 + 97.50×0.45 = 54.450 + 43.875 = 98.325 | **98.3** | **GOOD** |
| 2 | 250 | 3.5 | 96.67 | 84.375 | 96.6667×0.55 + 84.375×0.45 = 53.1667 + 37.9688 = 91.1354 | **91.1** | **GOOD** |
| 3 | 500 | 5.0 | 80.00 | 75.00 | 80.00×0.55 + 75.00×0.45 = 44.000 + 33.750 = 77.750 | **77.8** | **GOOD** |
| 4 | 650 | 7.5 | 72.00 | 70.83 | 72.00×0.55 + 70.8333×0.45 = 39.600 + 31.875 = 71.475 | **71.5** | **GOOD** |
| 5 | 900 | 12.0 | 58.67 | 63.33 | 58.6667×0.55 + 63.3333×0.45 = 32.2667 + 28.500 = 60.7667 | **60.8** | **MODERATE** |
| 6 | 2000 | 50.0 | 0.00 | 0.00 | 0×0.55 + 0×0.45 = 0 | **0.0** | **POOR** |
| 7 | 250 | *(null)* | 96.67 | — | **not calculated** (missing input) | **null** | **UNAVAILABLE** |

Verification notes:
- Example 1 sub-indices: `S_tds = 100 − 20×(215−200)/300 = 100 − 1.00 = 99.00`; `S_turb = 100 − 25×(1.4−1)/4 = 100 − 2.50 = 97.50`. ✅
- Example 3 rounds the tie `77.75 → 77.8`. ✅
- Example 4: `S_tds = 80×(1 − 150/1500) = 72.00`; `S_turb = 75×(1 − 2.5/45) = 70.8333`. ✅
- Example 5: `S_tds = 80×(1 − 400/1500) = 58.6667`; `S_turb = 75×(1 − 7/45) = 63.3333`. ✅
- Example 6: `S_tds = 80×(1 − 1500/1500) = 0`; `S_turb = 75×(1 − 45/45) = 0`. ✅
- Examples 4 and 5 deliberately show that the **score** and the **Parameter Rule Check** are independent outputs (see §6.3). No example sensor value was invented beyond these documented test vectors.

---

## 6. Parameter Rule Check (FINALIZED TERMINOLOGY — D8)

**Display name: `Parameter Rule Check`**

- Evaluates **only TDS and turbidity**.
- Result per parameter: **`PASS`** | **`WARNING`** | **`FAIL`** | **`UNAVAILABLE`**.
- The labels `SAFE` and `UNSAFE` are **not** used for this new output — `PASS` and `FAIL` replace them; `WARNING` keeps its wording (they remain only as stored values of legacy rows with their original four-parameter meaning).
- This check is **separate from the screening score** — both are always reported independently.

### 6.1 Per-parameter bands (existing thresholds, unchanged logic)

| Parameter | `PASS` | `WARNING` | `FAIL` |
|---|---|---|---|
| **TDS** (ppm) | `tds ≤ tds_max` (default ≤ 500) | `tds_max < tds ≤ 1.5 × tds_max` (≤ 750) | `tds > 1.5 × tds_max` (> 750) |
| **Turbidity** (NTU) | `turbidity ≤ turbidity_max` (default ≤ 5.0) | `turbidity_max < turbidity ≤ 2 × turbidity_max` (≤ 10.0) | `turbidity > 2 × turbidity_max` (> 10.0) |
| **either value missing / invalid** | — | — | **`UNAVAILABLE`** (never `PASS`) |

Every result identifies **which** parameter passed, warned or failed, together with the measured value, unit and a plain-language detail line (e.g. `"TDS (650.0 ppm) is moderately above the configured threshold (500.0 ppm)"`).

### 6.2 Overall result

Overall = worst status present, in the order:

```
FAIL  >  WARNING  >  UNAVAILABLE  >  PASS
```

- `FAIL` / `WARNING` are positive evidence of a problem and must never be masked by missing data.
- `UNAVAILABLE` outranks `PASS` so that an **incomplete check can never read `PASS`**.
- Missing data is therefore never treated as `PASS`.

### 6.3 Interpretation limits

- `PASS` means **only** that the two measured parameters were within their configured thresholds at that moment.
- **`PASS` does not mean potable, certified, verified or safe to drink.** The UI must not phrase a `PASS` result as confirmation that water is potable.
- Score and rule check can legitimately differ (example 4: score `GOOD` 71.5 while both parameters `WARNING`; example 5: score `MODERATE` 60.8 while both parameters `FAIL`) — they measure different things and must both be shown.

---

## 7. Preliminary Screening Status Bands (FINALIZED — D4)

Derived from `quality_score` only:

| Status | Score range | Explanation text |
|---|---|---|
| **`GOOD`** | `score ≥ 70` (70.0 – 100.0) | "Preliminary screening score for TDS and turbidity is within the configured acceptable range." |
| **`MODERATE`** | `40 ≤ score < 70` | "Preliminary screening score is partly outside the preferred range — review thresholds and inspect the supply." |
| **`POOR`** | `score < 40` (0.0 – 39.9) | "Preliminary screening score is well outside the acceptable range for TDS and turbidity." |
| **`UNAVAILABLE`** | `score = null` | "Screening score unavailable — a required sensor reading is missing or invalid." |

- Always labelled **"preliminary screening"**; never *certified*, *verified*, *guaranteed* or *safe to drink*.
- The UI must not convert `UNAVAILABLE` into any of the three scored bands.

---

## 8. Threshold Configuration

| Key | Default | Validation |
|---|---|---|
| `tds_max` | 500.0 ppm | `≥ 0`, finite |
| `turbidity_max` | 5.0 NTU | `≥ 0`, finite |
| `status_good_min` | 70.0 | `0 ≤ value ≤ 100` |
| `status_poor_max` | 40.0 | `0 ≤ value ≤ 100`, and `status_poor_max < status_good_min` |

- Delivered through the existing `GET /api/config` + `PUT /api/config` endpoints (no new endpoint).
- `1.5 × tds_max` and `2 × turbidity_max` FAIL boundaries are derived from these two thresholds at evaluation time.
- Changes take effect on the **next** assessment only; stored scores and stored rule results are **never recomputed retroactively**.
- Cross-field violations return `400` (mirroring today's checks). Legacy `ph_min`/`ph_max`/`temperature_min`/`temperature_max` keys remain readable but optional after the migration.

---

## 9. Invalid or Missing Sensor Readings

**Never fabricate a value.**

| Condition | Screening score | Parameter Rule Check |
|---|---|---|
| `tds` or `turbidity` is `null` / absent | `null`, status `UNAVAILABLE` (no partial score) | that parameter = `UNAVAILABLE`; overall per §6.2 |
| Value present but invalid (negative, non-finite, non-numeric, boolean, out of physical range) | Rejected by API → row never created (`422`) | n/a |
| Both values valid | Calculated per §5 | Both parameters evaluated per §6.1 |
| Model input missing (no pH) | Score unaffected — **the score never uses pH** | Rule check unaffected — it never uses pH |

---

## 10. Historical vs New Scores (FINALIZED — D3: store `score_method`)

| | Historical score | New screening score |
|---|---|---|
| Formula | 4 parameters (0.35/0.30/0.25/0.10) | **TDS 0.55 + turbidity 0.45** |
| Rule labels stored/displayed | `SAFE`/`WARNING`/`UNSAFE` (original meaning preserved) | storage unchanged; displayed as **Parameter Rule Check `PASS`/`WARNING`/`FAIL`** |
| `score_method` | `NULL` (or `FOUR_PARAM_LEGACY`) | `"TWO_PARAM_SCREENING"` |

- Legacy rows are **not backfilled** (no `UPDATE` of existing records).
- Charts, statistics and exports must group/label by `score_method`; the two generations are **never averaged or compared as equivalent**.
- Exports include `score_method` so readers can distinguish them.

---

## 11. Decision Status

| Decision | Status |
|---|---|
| D1 weights 0.55 / 0.45 | ✅ **FINALIZED** |
| D2 skip ML inference when pH missing (artifact untouched) | ✅ **FINALIZED** |
| D3 store `score_method` | ✅ **FINALIZED** |
| D4 bands GOOD ≥ 70, POOR < 40 | ✅ **FINALIZED** |
| D5 simulator two-channel default + optional legacy 4-channel | ✅ **FINALIZED** |
| D6 device API now, statistics API later | ✅ **FINALIZED** |
| D7 admin authentication addressed before deployment | ✅ **FINALIZED** (mechanism itself pending) |
| D8 Parameter Rule Check `PASS`/`WARNING`/`FAIL` | ✅ **FINALIZED** |
| Storage/persistence of per-parameter rule results for GET responses | ⏳ **PENDING** (Phase 10 field-level design) |
| Admin auth mechanism (token vs basic auth) | ⏳ **PENDING** (before deployment) |

---

## 12. Explicit Limitations

1. Two sensors cannot characterise overall water safety; many dangerous contaminants are invisible to both.
2. The score is deterministic arithmetic, not a validated regulatory index.
3. TDS conflates dissolved minerals, salts and metals; turbidity measures cloudiness only.
4. Calibration drift shifts both score and rule results; calibration is routine maintenance.
5. The ML model (pH/TDS/turbidity) never contributes to this score and returns `NULL` for readings without pH.
6. Neither a `GOOD` score nor a `PASS` rule check establishes that water is potable.

---

*Phase 9 documentation only — no scoring code was implemented or modified.*
