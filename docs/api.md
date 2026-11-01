# API Specification

Base URL: `/api`

> **Status key:** endpoints listed under *Implemented* are live and verified (Phases 1-5; the Phase 6 simulator produces the `SIMULATION` readings posted to `POST /api/readings`, and the Phase 7 React dashboard consumes these endpoints through its dev proxy). Endpoints listed under *Planned* do **not** exist yet and are reserved for later phases.
>
> **Metric naming:** the 0-100 composite metric returned by this API is called the **Water Quality Score** (`quality_score`). It is an internal prototype score, not an official Water Quality Index (WQI).
>
> **ML status:** `prediction` / `confidence` come from an **EXPERIMENTAL / ADVISORY** Random Forest model (test ROC-AUC 0.5522, POTABLE recall 0.0864) using `ph`, `tds`, `turbidity` only. It never certifies water and never overrides the Safety Rule Engine.
>
> **Phase 9 (final hardware scope):** a new **two-sensor ESP8266 contract** is specified at the bottom of this document under *Proposed Phase 9 Contract (NOT YET IMPLEMENTED)*. It is a design proposal only — the live API still requires `ph` and `temperature` and rejects the new payload with HTTP `422` today. See `docs/PHASE_9_MIGRATION_DESIGN.md`, `docs/PHASE_9_QUALITY_ASSESSMENT_DESIGN.md` and `docs/PHASE_9_IMPLEMENTATION_ROADMAP.md`.

---

## Implemented Endpoints

### 1. Health Check
- **`GET /health`**
  - Verifies the FastAPI process and MySQL connectivity.
  - Response:
    ```json
    {
      "status": "healthy",
      "service": "Smart Water Quality Monitoring API",
      "database": "connected",
      "timestamp": "2026-10-06T13:20:09.185366+00:00",
      "environment": "development",
      "version": "1.0.0"
    }
    ```
  - `status` is `healthy` when `database` is `connected`, otherwise `degraded`.

### 2. Water Quality Readings
- **`POST /api/readings`**
  - Ingests a water quality reading from the software simulator (`source: "SIMULATION"`, Phase 6 — software-generated data, **not** real hardware) or a future ESP32 (`source: "ESP32"`, not yet implemented).
  - The simulator (`simulator/simulator.py`) is the Phase 6 producer of `SIMULATION` readings: 10 selectable scenarios, realistic gradual sensor movement, `--interval` / `--count` / `--seed` options, posted to this endpoint only.
  - Runs the deterministic Safety Rule Engine, computes the Water Quality Score, runs the advisory ML inference (`ph`, `tds`, `turbidity` — temperature is never passed to the model), and persists the reading plus its assessment to MySQL.
  - Body:
    ```json
    {
      "device_id": "SIMULATOR-001",
      "ph": 7.2,
      "tds": 250.0,
      "turbidity": 2.1,
      "temperature": 27.5,
      "source": "SIMULATION"
    }
    ```
  - Response (HTTP `201`):
    ```json
    {
      "id": 66,
      "reading_id": 66,
      "device_id": "SIMULATOR-001",
      "ph": 7.2,
      "tds": 250.0,
      "turbidity": 2.1,
      "temperature": 27.5,
      "source": "SIMULATION",
      "timestamp": "2026-10-06T13:24:11+00:00",
      "quality_score": 97.4,
      "safety_status": "SAFE",
      "warning_message": null,
      "safety": {
        "status": "SAFE",
        "warning_message": null,
        "violated_parameters": []
      },
      "reading": {
        "id": 66,
        "device_id": "SIMULATOR-001",
        "ph": 7.2,
        "tds": 250.0,
        "turbidity": 2.1,
        "temperature": 27.5,
        "source": "SIMULATION",
        "timestamp": "2026-10-06T13:24:11+00:00",
        "quality_score": 97.4,
        "safety_status": "SAFE",
        "warning_message": null,
        "prediction": "POTABLE",
        "confidence": 0.567681
      },
      "prediction": "POTABLE",
      "confidence": 0.567681,
      "success": true
    }
    ```
  - `safety_status`: `SAFE` | `WARNING` | `UNSAFE` (deterministic rule engine, see `docs/architecture.md`).
  - `quality_score`: the **Water Quality Score**, always in `[0, 100]`.
  - `safety.violated_parameters`: names of out-of-threshold parameters (`pH`, `TDS`, `Turbidity`, `Temperature`); empty when `SAFE`.
  - `prediction`: **EXPERIMENTAL / ADVISORY** ML verdict — `POTABLE` or `NOT POTABLE`, or `null` if the model was unavailable/inference failed (safety assessment still succeeds in that case).
  - `confidence`: model probability of the predicted class, always in `[0, 1]`; `null` whenever `prediction` is `null`.
  - The two verdicts are **independent**: a `POTABLE` prediction never changes `safety_status`, and `safety_status` is never derived from the model. The ML model is weak (ROC-AUC ≈ 0.552) and must not be treated as a safety guarantee.
- **`GET /api/readings/latest`**
  - Returns the most recent reading with its attached assessment: `quality_score`, `safety_status`, `warning_message`, plus the stored `prediction` / `confidence` when ML ran (otherwise `null`).
  - Returns HTTP `404` if no readings exist.
- **`GET /api/readings/history?limit=100&start_date=...&end_date=...`**
  - Returns historical readings with their assessments, newest first.
  - `limit`: 1-1000 (default 100). `start_date` / `end_date`: optional UTC timestamps.
  - `prediction` / `confidence` on each item reflect the stored ML verdict (or `null`).

### 3. Configuration
- **`GET /api/config`**
  - Returns the current threshold configuration (pH min/max, TDS max, Turbidity max, Temp min/max).
- **`PUT /api/config`**
  - Updates the threshold configuration dynamically without restarting the application; takes effect on the next reading evaluation.
  - Body fields: `ph_min`, `ph_max`, `tds_max`, `turbidity_max`, `temperature_min`, `temperature_max`.

### 4. ML Predictions (EXPERIMENTAL / ADVISORY)
- **`GET /api/predictions/latest`**
  - Returns the most recent **stored** ML verdict (rows where `prediction` is not `null`), newest first.
  - Response (HTTP `200`):
    ```json
    {
      "id": 150,
      "reading_id": 156,
      "prediction": "POTABLE",
      "confidence": 0.555876,
      "quality_score": 90.0,
      "safety_status": "UNSAFE",
      "warning_message": "Temperature (60.0 °C) is severely outside safe range [10.0 - 35.0 °C]",
      "input_features": { "ph": 7.2, "tds": 200.0, "turbidity": 1.0 },
      "temperature_used": false,
      "ml_status": "EXPERIMENTAL",
      "disclaimer": "EXPERIMENTAL / ADVISORY ML prediction from a weak prototype model (test ROC-AUC 0.5522, POTABLE recall 0.0864). It is NOT a guarantee that water is safe to drink and it never overrides the Safety Rule Engine.",
      "timestamp": "2026-10-06T17:02:51"
    }
    ```
  - `prediction`: `POTABLE` | `NOT POTABLE`; `confidence`: model probability, always in `[0, 1]`.
  - `input_features`: exactly the values fed to the model (`ph`, `tds`, `turbidity`); `temperature_used` is always `false`.
  - `safety_status` / `quality_score` / `warning_message` belong to the **rule engine**, not the model — both verdicts are returned together so disagreement is visible (e.g. `safety_status: "UNSAFE"` with `prediction: "POTABLE"`).
  - Returns HTTP `404` (`"No ML prediction stored yet."`) when no ML verdict has been stored, e.g. while the model is unavailable.
  - Note: rows written before Phase 5 (and rows created while the model failed) have `prediction = null` and are skipped by this endpoint.

---

## Planned Endpoints (Not Yet Implemented)

These endpoints are reserved for later phases. Calling them today returns HTTP `404`.

### Statistics
- **`GET /api/statistics`**
  - Will return aggregate counts, potability ratio, parameter averages, and mean Water Quality Score.

### Device Management
- **`GET /api/devices`**
  - Will return all registered devices with active/offline status based on last-seen heartbeat.
- **`GET /api/devices/{device_id}`**
  - Will return details and the latest reading for a specific device.

---

## Proposed Phase 9 Contract (NOT YET IMPLEMENTED)

> **Status: PROPOSAL — this section describes a contract that does not exist yet.**
> As of Phase 9 nothing above has changed: `POST /api/readings` still **requires** `ph` and `temperature` and returns **HTTP 422** for the payload below, `source: "ESP8266"` is **not yet a valid enum value**, and `quality_score` is still the legacy four-parameter score.
> Implementation is scheduled for Phase 10 after approval of `docs/PHASE_9_MIGRATION_DESIGN.md`. Design references: `docs/PHASE_9_QUALITY_ASSESSMENT_DESIGN.md` (score), `docs/PHASE_9_DASHBOARD_SPECIFICATION.md` (consumers).

### Hardware scope
ESP8266 NodeMCU + ADS1115 ADC + TDS sensor + turbidity sensor. **No pH sensor. No temperature sensor.**

### 5. New Hardware Ingestion — `POST /api/readings` *(proposed)*
- Required fields: `device_id`, `tds`, `turbidity`, `source`.
- Optional legacy fields: `ph`, `temperature` — **omitted or `null` for hardware readings**. Values are never inferred, defaulted or fabricated.

**Request (ESP8266):**
```json
{
  "device_id": "NODEMCU-001",
  "tds": 250.0,
  "turbidity": 3.5,
  "source": "ESP8266"
}
```
**Request (legacy simulator, still accepted):**
```json
{
  "device_id": "SIMULATOR-001",
  "ph": 7.2,
  "tds": 250.0,
  "turbidity": 2.1,
  "temperature": 27.5,
  "source": "SIMULATION"
}
```
Explicit `null` for the legacy fields is equivalent to omitting them:
```json
{
  "device_id": "NODEMCU-001",
  "tds": 250.0,
  "turbidity": 3.5,
  "ph": null,
  "temperature": null,
  "source": "ESP8266"
}
```

**Response (HTTP `201` — hardware reading, proposed):**
```json
{
  "id": 412,
  "reading_id": 412,
  "device_id": "NODEMCU-001",
  "ph": null,
  "tds": 250.0,
  "turbidity": 3.5,
  "temperature": null,
  "source": "ESP8266",
  "timestamp": "2026-10-30T14:02:11+00:00",
  "quality_score": 91.1,
  "score_method": "TWO_PARAM_SCREENING",
  "screening_status": "GOOD",
  "screening_explanation": "Preliminary screening score for TDS and turbidity is within the configured acceptable range.",
  "parameter_rule_check": {
    "label": "Parameter Rule Check",
    "status": "PASS",
    "parameters": {
      "tds": { "value": 250.0, "unit": "ppm", "status": "PASS", "detail": null },
      "turbidity": { "value": 3.5, "unit": "NTU", "status": "PASS", "detail": null }
    },
    "unavailable_parameters": [],
    "scope": "TDS and turbidity only",
    "disclaimer": "Passing this two-parameter check does NOT certify the water as potable or safe to drink. Laboratory testing is required."
  },
  "reading": { "id": 412, "device_id": "NODEMCU-001", "ph": null, "tds": 250.0, "turbidity": 3.5, "temperature": null, "source": "ESP8266", "timestamp": "2026-10-30T14:02:11+00:00", "quality_score": 91.1, "prediction": null, "confidence": null },
  "prediction": null,
  "confidence": null,
  "ml_status": "UNAVAILABLE",
  "ml_status_reason": "PH_NOT_MEASURED",
  "success": true
}
```
Field-by-field notes for this example (`tds = 250.0`, `turbidity = 3.5`, defaults `tds_max = 500`, `turbidity_max = 5.0`):
- `quality_score` **91.1** = `round(96.6667×0.55 + 84.375×0.45, 1) = round(91.1354, 1)` — verified example 2 of `PHASE_9_QUALITY_ASSESSMENT_DESIGN.md` §5.1.
- `score_method` **`TWO_PARAM_SCREENING`** identifies the formula used (legacy rows carry `FOUR_PARAM_LEGACY` / `null`).
- `screening_status` **`GOOD`** (score ≥ 70).
- `parameter_rule_check.status` **`PASS`** — both `tds ≤ 500` and `turbidity ≤ 5.0`.
- `prediction` / `confidence` are **`null`** because pH was not measured; `ml_status` / `ml_status_reason` say so explicitly.
- The legacy top-level `safety_status` / `safety` block returned by the **live** API is **not** shown here: for new two-parameter rows the proposed display field is `parameter_rule_check` (labels `PASS`/`WARNING`/`FAIL`). The `predictions.safety_status` storage column is unchanged by the migration; how legacy rows expose their historical `SAFE`/`WARNING`/`UNSAFE` meaning alongside the new field is a **pending Phase 10 field-compatibility decision** (roadmap pending item P1).

**Response (HTTP `201` — legacy reading with pH, proposed):** identical shape, but `ph`/`temperature` carry their values, `score_method` is `FOUR_PARAM_LEGACY` (or `TWO_PARAM_SCREENING` if written after the cutover by a pH-providing client), `prediction` / `confidence` / `ml_status: "AVAILABLE"` are populated exactly as today, and `safety_status` keeps its historical four-parameter meaning.

**Response (HTTP `201` — example with rule violations):** for `tds = 650.0`, `turbidity = 7.5` the proposed response carries `quality_score: 71.5`, `screening_status: "GOOD"`, and
```json
"parameter_rule_check": {
  "label": "Parameter Rule Check",
  "status": "WARNING",
  "parameters": {
    "tds": { "value": 650.0, "unit": "ppm", "status": "WARNING", "detail": "TDS (650.0 ppm) is above the configured threshold (500.0 ppm)." },
    "turbidity": { "value": 7.5, "unit": "NTU", "status": "WARNING", "detail": "Turbidity (7.5 NTU) is above the configured threshold (5.0 NTU)." }
  },
  "unavailable_parameters": [],
  "scope": "TDS and turbidity only",
  "disclaimer": "Passing this two-parameter check does NOT certify the water as potable or safe to drink. Laboratory testing is required."
}
```
This deliberately illustrates that the **screening score** and the **Parameter Rule Check** are two separate outputs that may differ, and that neither certifies potability.

### How missing pH / temperature are represented
| Layer | Representation |
|---|---|
| Request | field absent, or explicitly `null` |
| Storage | column value `NULL` (migration: `PHASE_9_MIGRATION_DESIGN.md`) |
| Response | `"ph": null`, `"temperature": null` — **never `0`, never a default, never an inferred value** |
| Assessment | pH/temperature take **no part** in the two-parameter score or the Parameter Rule Check; nothing is reported as `SAFE`/`PASS` on their behalf |
| Dashboard | value rendered as `—` + "not measured" (pH/temperature are not displayed at all in the new UI) |

### Validation and errors (proposed, mirrors current behaviour)
| Condition | Result |
|---|---|
| missing `tds` or `turbidity`, non-numeric, boolean, negative | `422` with field detail |
| missing `device_id`, empty/oversized | `422` |
| `source` not in `SIMULATION` \| `ESP32` \| `ESP8266` | `422` |
| `ph`/`temperature` omitted or `null` | **accepted** (`201`) |
| `ph`/`temperature` supplied out of range (ph 0–14, temp −10…100) | `422` |
| DB unavailable | `500` controlled error (unchanged) |

### ML prediction availability (proposed behaviour)
- **New readings (no pH):** `prediction: null`, `confidence: null`, `ml_status: "UNAVAILABLE"`, `ml_status_reason: "PH_NOT_MEASURED"`. The existing 3-feature model artifact is **not retrained, not modified, not bypassed with fake input** — it simply cannot run, so no verdict is produced.
- **Unavailable ≠ negative:** `prediction: null` means *no ML verdict was produced*; `prediction: "NOT POTABLE"` means *the model produced a negative verdict*. They are distinct JSON values and must never be conflated in the UI.
- **Legacy readings (pH present):** ML runs as today; stored verdicts remain retrievable via `GET /api/predictions/latest`, which continues to filter on non-null predictions (so it may return a **legacy** reading — the response's `timestamp` / `input_features` identify it).
- The two-parameter screening score is computed by the deterministic scoring service and **never** by the ML model.

### Two-parameter assessment (proposed) — two separate outputs
**1. Preliminary screening score**
- `quality_score` = `round((S_tds × 0.55) + (S_turbidity × 0.45), 1)` from **TDS + turbidity only**, always in `[0, 100]`. Weights **0.55 / 0.45 finalized** (D1). If either input is missing or invalid the score is **`null`** — a partial score is never calculated. Computed by the deterministic scoring service and **never** by the ML model.
- `score_method`: `"TWO_PARAM_SCREENING"` (new) vs `"FOUR_PARAM_LEGACY"` / `null` (historical) — legacy and new scores must never be averaged or compared as equivalent (D3).
- `screening_status`: `GOOD` (score ≥ 70) | `MODERATE` (40 ≤ score < 70) | `POOR` (score < 40) | `UNAVAILABLE` (score `null`) — bands configurable via `GET/PUT /api/config` (D4).

**2. Parameter Rule Check** (display name: **Parameter Rule Check**, D8)
- Evaluates **TDS and turbidity only**; pH and temperature take no part.
- Per-parameter and overall labels: **`PASS`** | **`WARNING`** | **`FAIL`** (and **`UNAVAILABLE`** when a value is missing/invalid — missing data is **never** reported as `PASS`).
- Bands: TDS `PASS ≤ tds_max` (500) · `WARNING ≤ 1.5 × tds_max` (750) · `FAIL` above; Turbidity `PASS ≤ turbidity_max` (5.0) · `WARNING ≤ 2 × turbidity_max` (10.0) · `FAIL` above.
- Overall = worst status, ordered `FAIL > WARNING > UNAVAILABLE > PASS`.
- `PASS` means only that the two measured parameters were within their thresholds — **it is not a statement that the water is potable**.
- The legacy `SAFE` / `WARNING` / `UNSAFE` labels are **not** used for this new output; they remain only as stored values of historical rows with their original four-parameter meaning.

- **Disclaimer:** both outputs are preliminary screening information only — TDS and turbidity cannot detect every harmful contaminant (bacteria, viruses, dissolved metals, nitrates, pesticides, etc.). Laboratory testing is required to confirm drinking-water safety.

### Planned config fields (proposed)
`tds_max`, `turbidity_max`, `status_good_min`, `status_poor_max` (+ legacy `ph_min`, `ph_max`, `temperature_min`, `temperature_max` retained but optional after migration).
