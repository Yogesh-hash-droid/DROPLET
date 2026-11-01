# Phase 10 — Backend Implementation Plan (PLANNING ONLY)

> **Status:** PLANNING DOCUMENT — **no backend runtime code, database, simulator, frontend, ML artifact or firmware has been modified.**
> **Created by:** repository inspection of the actual saved code (not from memory of earlier audits).
> **Correction round applied:** R-2 = **B1 FINAL**, R-3 = **REQUIRED FINAL**, P1 = **SEPARATE FINAL**; Workstream/Gate numbering corrected (Step 9 now part of Workstream A / Gate 2); device **connectivity** separated from **sensor health**. See §7.2, §7.7, §11, §12.
> **Target hardware scope:** ESP8266 NodeMCU + ADS1115 ADC + TDS sensor + Turbidity sensor. **No pH sensor. No temperature sensor.**
> **Backend stack:** Python / FastAPI / Pydantic / SQLAlchemy / MySQL (pymysql), scikit-learn joblib artifact.
> **Companion documents:** `docs/PHASE_9_QUALITY_ASSESSMENT_DESIGN.md` · `docs/PHASE_9_MIGRATION_DESIGN.md` · `docs/PHASE_9_DASHBOARD_SPECIFICATION.md` · `docs/PHASE_9_IMPLEMENTATION_ROADMAP.md` · `docs/api.md` · `database/migrations/phase9_scope_reconciliation.sql`
>
> **Restrictions honored while writing/correcting this plan:** no source edits, no SQL execution, no MySQL connection, no package changes, no ML retraining, no migration-SQL edits, no Phase 11+ work. The only file edited is this document.

---

## 1. Current Backend Architecture (as inspected)

### 1.1 SQLAlchemy models and relationships

| Model (file) | Table | Key columns (from source) | Relationships |
|---|---|---|---|
| `Device` (`backend/app/models/device.py`) | `devices` | `device_id` (unique, str 64), `device_name`, `source` (`DeviceSource`), `status` (`DeviceStatus`), `last_seen` (nullable), `created_at` | `readings` → `WaterReading` (cascade all, delete-orphan) |
| `WaterReading` (`backend/app/models/water_reading.py`) | `water_readings` | `device_id` (FK → `devices.device_id`, CASCADE), `ph` **NOT NULL**, `tds` NOT NULL, `turbidity` NOT NULL, `temperature` **NOT NULL**, `source` (`DeviceSource`, default `SIMULATION`), `timestamp` | `device` (many→one), `assessment` (one→one `Prediction`, cascade all, delete-orphan) |
| `Prediction` (`backend/app/models/prediction.py`) | `predictions` | `reading_id` (FK, unique, CASCADE), `prediction` (`PotabilityResult`, **nullable**), `confidence` (nullable), `quality_score` (**NOT NULL**), `safety_status` (`SafetyStatus`, **NOT NULL**), `warning_message` (nullable), `timestamp` | `reading` (many→one `WaterReading`) |
| `SystemConfig` (`backend/app/models/system_config.py`) | `system_config` | `id` (pk, default 1), `ph_min` 6.5, `ph_max` 8.5, `tds_max` 500.0, `turbidity_max` 5.0, `temperature_min` 10.0, `temperature_max` 35.0 — **all six NOT NULL** — `updated_at` (onupdate) | none |

Enums (Python-side, values persisted via `values_callable=_enum_db_values` in `prediction.py`):
- `DeviceSource` = `SIMULATION` | `ESP32` — **no `ESP8266` member today** (`models/device.py` L9-11).
- `DeviceStatus` = `ONLINE` | `OFFLINE` (device **connectivity** only — see §3.4).
- `PotabilityResult` = `POTABLE` | `NOT POTABLE`; `SafetyStatus` = `SAFE` | `WARNING` | `UNSAFE`.
- ORM convenience properties on `WaterReading`: `prediction`, `confidence`, `quality_score`, `safety_status`, `warning_message` (all proxy `self.assessment`).

### 1.2 Pydantic request/response schemas

| Schema (file) | Role | Notable constraints **today** |
|---|---|---|
| `WaterReadingBase` / `WaterReadingCreate` (`app/schemas/water_reading.py`) | POST /api/readings body | `ph` **required** (0–14), `tds` required (≥0), `turbidity` required (≥0), `temperature` **required** (−10–100), `source: Literal["SIMULATION","ESP32"]`; `_reject_boolean_as_number` field validator (mode="before") rejects `bool` for all four numeric fields |
| `WaterReadingResponse` | GET /latest, /history rows; embedded `reading` | extends base; adds `id`, `timestamp`, `quality_score` (Optional), `safety_status` (Optional Literal SAFE/WARNING/UNSAFE), `warning_message`, `prediction`, `confidence` |
| `SafetyInfo` | POST response sub-object | `status` Literal SAFE/WARNING/UNSAFE, `warning_message`, `violated_parameters: List[str]` |
| `ReadingIngestionResponse` | POST /api/readings response | `ph`, `temperature` **non-optional floats**; `quality_score: float` (required); `safety_status`; `safety: SafetyInfo`; `reading: WaterReadingResponse`; `prediction`/`confidence` Optional; `success: bool` |
| `PredictionResponse` / `LatestPredictionResponse` (`app/schemas/prediction.py`) | GET /api/predictions/latest | `prediction` **required non-null**; adds `input_features`, `temperature_used=False`, `ml_status` (default "EXPERIMENTAL"), `disclaimer` |
| `DeviceResponse` (`app/schemas/device.py`) | (unused by any router today) | `source: Literal["SIMULATION","ESP32"]` |
| `SystemConfigBase` / `SystemConfigUpdate` / `SystemConfigResponse` (`app/schemas/system_config.py`) | GET/PUT /api/config | Base/Response require all six thresholds; Update makes all six optional; **no band-threshold fields today** |

### 1.3 Reading creation and persistence

`app/services/reading_service.py` → `create_reading_with_assessment(db, reading_in)` returns `Tuple[WaterReading, SafetyEvaluationResult, QualityScoreBreakdown, Optional[MLInferenceResult]]`. Sequence (L36-122):
1. `config_service.get_system_config(db)`.
2. Device upsert: existing row → update `last_seen`/`status=ONLINE`/`source`; new row → `Device(...)` with `device_name = f"{source.capitalize()} Node ({device_id})"`.
3. `WaterReading(...)` with **`round(float(...), 2)` applied unconditionally to all four sensors** (L63-66) — will crash on `None` after the model is relaxed → must be conditionalized.
4. `safety_service.evaluate_safety(ph, tds, turbidity, temperature, config)`.
5. `quality_service.calculate_water_quality_score(ph, tds, turbidity, temperature, config)`.
6. `ml_service.predict_reading(ph, tds, turbidity)` in `try/except` (ML failure → `None`, never breaks the flow).
7. `Prediction(reading_id, prediction, confidence, quality_score=quality_result.overall_score, safety_status=safety_result.status, warning_message, timestamp)` → `db.commit()` → `db.refresh()`.

Read paths: `get_latest_reading(db)` (order timestamp desc, id desc) and `get_readings_history(db, limit=100, start_date, end_date)`.

### 1.4 Quality assessment service

`app/services/quality_service.py::calculate_water_quality_score(ph, tds, turbidity, temperature, config) -> QualityScoreBreakdown(overall_score, sub_scores, weights)`. Four sub-indices with weights **0.35 / 0.30 / 0.25 / 0.10**, clamped [0,100], final `round(..., 1)`. TDS and turbidity sub-index curves in this file are the ones reused unchanged by the two-parameter design (Phase 9 design §3).

### 1.5 Safety/rule-check service

`app/services/safety_service.py::evaluate_safety(ph, tds, turbidity, temperature, config) -> SafetyEvaluationResult(status, warning_message, violated_parameters, parameter_evaluations)`. Four parameter evaluations (pH, TDS, Turbidity, Temperature) using `SafetyStatus` SAFE/WARNING/UNSAFE. Threshold logic to be **reused** for the two-parameter Parameter Rule Check:
- TDS: PASS ≤ `tds_max`; WARNING ≤ `tds_max × 1.5`; FAIL(UNSAFE) > `tds_max × 1.5` (L92-112).
- Turbidity: PASS ≤ `turbidity_max`; WARNING ≤ `turbidity_max × 2.0`; FAIL > `turbidity_max × 2.0` (L118-138).

### 1.6 ML inference service and model validation

`app/ml/service.py`:
- `FEATURE_COLUMNS = ("ph","tds","turbidity")`; `PHYSICAL_RANGES` rejects null/non-finite/out-of-range; `MLServiceError`; `MLInferenceResult` (prediction, confidence [0,1], probabilities, features, model_trained_at, status "EXPERIMENTAL").
- `MLInferenceService`: lazy thread-safe singleton load; artifact validation (dict with `model`, `feature_columns` must equal `FEATURE_COLUMNS`, `temperature_used` must not be True, `predict_proba` must exist).
- `predict_reading(ph, tds, turbidity) -> Optional[MLInferenceResult]` — returns `None` on any failure (logged, never fabricated). **Note:** `_validate_features` raises on `None` pH, so a `None` pH passed today would produce `None` result *without* a distinguishable reason → Phase 10 must decide `PH_NOT_MEASURED` **before** calling the wrapper.
- Artifact: `ml/models/water_potability_model.joblib` (untouched; ROC-AUC 0.5522, POTABLE recall 0.0864 → stays EXPERIMENTAL/ADVISORY). **The ML artifact stays unchanged; when pH is missing, inference is skipped and prediction/confidence remain NULL (§6).**

### 1.7 Configuration service and system configuration

`app/services/config_service.py`: `get_system_config(db)` auto-provisions row `id=1` from `Settings.DEFAULT_PH_MIN/MAX, DEFAULT_TDS_MAX, DEFAULT_TURBIDITY_MAX, DEFAULT_TEMP_MIN/MAX`; `update_system_config(db, SystemConfigUpdate)` applies cross-field checks (`ph_min < ph_max`, `temperature_min < temperature_max` → HTTP 400) then `setattr` for `exclude_unset` fields. `app/config.py::Settings` also holds `DEVICE_OFFLINE_THRESHOLD_SECONDS = 30` (**currently unused by any code**) and `MODEL_PATH` / `METRICS_PATH`. **No band-threshold settings exist today** (they will be DB-backed — final decision B1, §7.2).

### 1.8 API routers and endpoint behaviour

| Router (file) | Endpoint | Behaviour (as implemented) |
|---|---|---|
| `app/routers/readings.py` | `POST /api/readings` (201) | Builds `ReadingIngestionResponse` manually from service returns; generic `except Exception` → HTTP 500 "Failed to persist reading and evaluation" |
| | `GET /api/readings/latest` | `WaterReadingResponse`; 404 "No water quality readings found." |
| | `GET /api/readings/history` | `limit` (1–1000, default 100), `start_date`, `end_date`; list of `WaterReadingResponse` |
| `app/routers/predictions.py` | `GET /api/predictions/latest` | Rows with `prediction IS NOT NULL AND confidence IS NOT NULL` (L29) → 404 "No ML prediction stored yet."; already naturally excludes NULL predictions |
| `app/routers/config.py` | `GET /api/config`, `PUT /api/config` | Thin wrappers over `config_service`; **PUT is unauthenticated** (P2 pending) |
| `app/main.py` | `/health`, `/` | `Base.metadata.create_all` at import (best-effort); lifespan `get_ml_service().warm_up()`; CORS from Settings; routers mounted under `/api` |

**No `devices` or `statistics` router exists.** (D6: device API in Phase 10, statistics later.)

### 1.9 Backend tests and fixtures (no `conftest.py` exists)

119 tests across 9 files:
- `test_readings_unit.py` (11): in-memory SQLite (`StaticPool`), `app.dependency_overrides[get_db]` via autouse fixture — **the pattern Phase 10 extends**; covers valid 6-field payload, out-of-range/boolean rejection.
- `test_phase3_services.py` (31): pure service tests via `make_config()` building a detached `SystemConfig()` (no DB) — `TestSafetyRuleEngine`, `TestQualityScoreService` exercise the **4-parameter** functions directly.
- `test_phase3_api.py` (13): live-MySQL API tests; several assert safety verdicts driven by **pH/temperature** (e.g. `test_post_reading_abnormal_ph_warning`, `test_post_reading_severely_acidic_unsafe`) — semantics change under the 2-parameter rule check (see §8 step 10).
- `test_phase5_ml_api.py` (16): ML service unit tests + live-API ML tests incl. `test_temperature_unsafe_ml_potable_disagreement` (temperature-driven UNSAFE) and `test_ml_failure_keeps_safety_working` (monkeypatch pattern).
- `test_readings_integration.py` (4) & `test_simulator_integration.py` (4): live MySQL required.
- `test_simulator.py` (17): simulator module only (exact 6-key payload assertions) — backend contract must keep accepting that payload.
- `test_ml_pipeline.py` (14): training pipeline (re-run only; no retraining of the shipped artifact).
- `test_health.py` (2).

### 1.10 Database schema and migration draft

- Baseline `database/schema.sql`: 4 tables + seed rows; `source ENUM('SIMULATION','ESP32')` on both `devices` and `water_readings`; `water_readings.ph/temperature FLOAT NOT NULL`; `predictions.quality_score FLOAT NOT NULL`; `system_config` all-NOT-NULL + `CHECK (id = 1)`.
- Draft `database/migrations/phase9_scope_reconciliation.sql` (DRAFT/NOT FOR EXECUTION, verified in the Phase 9 final audit and **amended in Phase 10 Step 4**): **6 executable DDL statements** — (1) one combined `ALTER TABLE water_readings` (ph/temperature → NULL, source enum widened with ESP8266), (2) `ALTER TABLE system_config` (four pH/temperature threshold columns → NULL), (3) `ALTER TABLE devices` (source enum widened), (4) guarded `ALTER TABLE predictions ADD COLUMN score_method ENUM('FOUR_PARAM_LEGACY','TWO_PARAM_SCREENING') NULL DEFAULT NULL`, (5) guarded `ALTER TABLE system_config ADD COLUMN status_good_min FLOAT NOT NULL DEFAULT 70.0, status_poor_max FLOAT NOT NULL DEFAULT 40.0` (B1, draft §4B), (6) guarded `ALTER TABLE predictions ADD INDEX idx_score_method (score_method)` (model parity, draft §4C). Steps 4–6 each carry an `information_schema` re-run guard.
- **Review finding A → RESOLVED by final decision R-2 = B1:** `status_good_min` / `status_poor_max` were absent from the original draft; the plan required them as a migration addition (§7.2). *Update (Phase 10 Step 4, 2026-10-31): the draft WAS amended to add them (Section 4B), together with the `idx_score_method` index (Section 4C). The file remains DRAFT / unexecuted — execution still requires Gate 3 explicit approval.*
- **Review finding B → RESOLVED by final decision R-3 = REQUIRED:** `score_method` exists neither in `app/models/prediction.py` nor in `database/schema.sql`; draft step 4 changes from *optional* to **required** (§7.2) and the column must exist **before** backend code that relies on it is deployed.

---

## 2. Target Backend Architecture and Current→Target Changes

### 2.1 Target architecture (Phase 10 outcome)

```
ESP8266 (HTTP JSON, source="ESP8266", tds+turbidity only)
   │
   ▼
POST /api/readings ──► WaterReadingCreate (ph/temperature Optional, source+ESP8266)
   │
   ▼
reading_service.create_reading_with_assessment
   ├── config_service.get_system_config            (legacy keys optional; band keys status_good_min/status_poor_max — B1)
   ├── device upsert                                (DeviceSource.ESP8266 valid)
   ├── WaterReading row                             (ph=NULL, temperature=NULL persisted)
   ├── quality_service.calculate_screening_score    (2-param, 0.55/0.45, score_method="TWO_PARAM_SCREENING")
   ├── safety_service.evaluate_parameter_rule_check (PASS/WARNING/FAIL/UNAVAILABLE, TDS+turbidity only)
   ├── ml_service.predict_reading  ── skipped when ph is NULL → ml_status=UNAVAILABLE / PH_NOT_MEASURED
   └── Prediction row (score_method REQUIRED column; safety_status storage mirror; prediction/confidence NULL when ML skipped)
   │
   ▼
GET /api/readings/latest | /history   (score_method separates historical vs new assessments — P1)
GET /api/devices                      (device connectivity only, not sensor health)
GET /api/predictions/latest           (real verdicts only)
```

### 2.2 Current → target change summary (overview; details in §8)

| Area | Current | Target |
|---|---|---|
| Request `ph`/`temperature` | required (422 if absent) | Optional; absent/`null` → stored `NULL`; never fabricated |
| `source` | `SIMULATION`/`ESP32` | + `ESP8266` (both legacy values kept) |
| Score | 4-param (0.35/0.30/0.25/0.10) | 2-param `round(S_tds×0.55 + S_turb×0.45, 1)` + `score_method` (REQUIRED column) |
| Screening status | (frontend bands only) | `GOOD`/`MODERATE`/`POOR`/`UNAVAILABLE`, bands DB-backed: `status_good_min`=70.0, `status_poor_max`=40.0 (**B1 final**) |
| Rule engine display | SAFE/WARNING/UNSAFE (4 params) | **Parameter Rule Check** `PASS`/`WARNING`/`FAIL` (+`UNAVAILABLE`) on TDS+turbidity for **new** records; historical rows keep their original SAFE/WARNING/UNSAFE meaning untouched (**P1 final**) |
| Assessment separation | single, undifferentiated | read endpoints discriminate historical vs new via `score_method`; historical assessment fields are returned verbatim, never re-mapped or reconstructed |
| ML | runs when inputs valid | runs **only when ph present**; else `prediction=null`, `confidence=null`, `ml_status="UNAVAILABLE"`, `ml_status_reason="PH_NOT_MEASURED"` |
| Device API | none | `GET /api/devices`, `GET /api/devices/{device_id}` — **device connectivity only**; sensor health stays `UNKNOWN` without diagnostics |
| Config | 6 required thresholds | 6 legacy thresholds (values preserved, fields optional) + `status_good_min`/`status_poor_max` (70.0/40.0, DB-backed, B1) |

### 2.3 Non-goals of Phase 10

No simulator changes (Phase 12), no frontend changes (Phase 13), no firmware (Phase 14), no statistics API (later, with Analytics), no admin auth implementation (P2 pending, before deployment), no ML retraining (never without explicit approval), no hardware diagnostics/firmware work (sensor health simply remains UNKNOWN), no deletion of legacy code paths (`evaluate_safety` and `calculate_water_quality_score` are retained for the historical-assessment path and their 31 existing service tests until a later cleanup phase).

---

## 3. Target Backend Contract (Task 2)

### 3.1 Request — `POST /api/readings`

```json
{
  "device_id": "NODEMCU-001",
  "tds": 250.0,
  "turbidity": 3.5,
  "source": "ESP8266"
}
```

Proposed schema (all changes in `backend/app/schemas/water_reading.py`):

```python
class WaterReadingBase(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    ph: Optional[float] = Field(None, ge=0.0, le=14.0)          # was required
    tds: float = Field(..., ge=0.0)                              # required, unchanged
    turbidity: float = Field(..., ge=0.0)                        # required, unchanged
    temperature: Optional[float] = Field(None, ge=-10.0, le=100.0)  # was required
    source: Literal["SIMULATION", "ESP32", "ESP8266"] = Field(...)  # ESP8266 added

    @field_validator("ph", "tds", "turbidity", "temperature", mode="before")
    @classmethod
    def _reject_boolean_as_number(cls, value):
        if isinstance(value, bool):                      # None passes through untouched
            raise ValueError("numeric sensor value cannot be a boolean")
        return value
```

Validation rules:
- `device_id`: 1–64 chars, required.
- `tds`, `turbidity`: **required**; `≥ 0.0`; booleans rejected (422); non-numeric rejected (422). Missing/null/`-1` → **HTTP 422** (never stored, never defaulted).
- `ph`, `temperature`: optional; when present must be numeric, non-boolean and in range (`ph` 0–14, `temperature` −10–100); when absent or `null` → stored `NULL`, **never fabricated**.
- `source`: `SIMULATION` | `ESP32` | `ESP8266` (legacy values preserved; ESP32 accepted for historical hardware).
- Unknown extra fields: rejected by Pydantic default (unchanged).
- Rounding to 2 decimals retained, applied only to non-`None` values.

Legacy compatibility: the simulator's exact 6-key payload (`device_id`, `ph`, `tds`, `turbidity`, `temperature`, `source="SIMULATION"`) remains valid unchanged; rows written through it still receive `score_method = "TWO_PARAM_SCREENING"` (they are new rows), while **historical** 4-parameter rows are identified by `score_method IS NULL`.

### 3.2 Response — `POST /api/readings` (201)

New/changed response fields (kept additive so the current React UI keeps working until Phase 13):

```python
class ParameterRuleCheckParameter(BaseModel):      # new (schemas/parameter_rule_check.py)
    value: Optional[float]
    unit: Literal["ppm", "NTU"]
    status: Literal["PASS", "WARNING", "FAIL", "UNAVAILABLE"]
    detail: Optional[str] = None

class ParameterRuleCheckInfo(BaseModel):           # new
    label: Literal["Parameter Rule Check"] = "Parameter Rule Check"
    status: Literal["PASS", "WARNING", "FAIL", "UNAVAILABLE"]
    parameters: Dict[str, ParameterRuleCheckParameter]   # keys: "tds", "turbidity"
    unavailable_parameters: List[str] = []
    scope: str = "TDS and turbidity only"
    disclaimer: str = "Passing this two-parameter check does NOT certify the water as potable or safe to drink. Laboratory testing is required."

class ReadingIngestionResponse(BaseModel):
    # existing fields retained; ph/temperature become Optional
    id: int; reading_id: int; device_id: str
    ph: Optional[float] = None
    tds: float; turbidity: float
    temperature: Optional[float] = None
    source: Literal["SIMULATION", "ESP32", "ESP8266"]
    timestamp: datetime
    quality_score: float                      # tds/turbidity are mandatory -> always computable
    score_method: Literal["TWO_PARAM_SCREENING", "FOUR_PARAM_LEGACY"]  # NEW (REQUIRED column, R-3)
    screening_status: Literal["GOOD", "MODERATE", "POOR", "UNAVAILABLE"]  # NEW (bands from B1 config)
    screening_explanation: Optional[str] = None                          # NEW
    parameter_rule_check: ParameterRuleCheckInfo                        # NEW - primary assessment
    safety_status: Literal["SAFE", "WARNING", "UNSAFE"]   # DEPRECATED compatibility mirror only (P1)
    warning_message: Optional[str] = None                # mirrored detail text (deprecated)
    safety: SafetyInfo                        # DEPRECATED compatibility mirror; contents = 2-parameter results
    reading: WaterReadingResponse             # now nullable ph/temperature
    prediction: Optional[Literal["POTABLE", "NOT POTABLE"]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    ml_status: Literal["AVAILABLE", "UNAVAILABLE"] = "AVAILABLE"           # NEW
    ml_status_reason: Optional[Literal["PH_NOT_MEASURED", "MODEL_UNAVAILABLE", "INFERENCE_FAILED"]] = None  # NEW
    success: bool = True
```

**P1 (SEPARATE) — assessment representation rules for new records:**
- `parameter_rule_check` is the **primary and authoritative** assessment output for new two-sensor records; its vocabulary is `PASS`/`WARNING`/`FAIL`/`UNAVAILABLE`.
- `safety_status` / `safety` remain in the response **only** as deprecated compatibility mirrors for the existing frontend (the `predictions.safety_status` column is NOT NULL and its storage enum is unchanged); they are never presented as the primary assessment terminology for new records.
- Storage mapping for new rows is a persistence detail only: PASS→`SAFE`, WARNING→`WARNING`, FAIL→`UNSAFE` (overall-UNAVAILABLE→`WARNING`, defensive-only).
- A screening result is **never represented as certification**; both outputs carry the laboratory-testing disclaimer.

Example — hardware reading, verified against the formula (`S_tds(250)=96.6667`, `S_turb(3.5)=84.375` → 91.1354 → **91.1**; `parameter_rule_check`: both PASS):

```json
{
  "id": 412, "reading_id": 412, "device_id": "NODEMCU-001",
  "ph": null, "tds": 250.0, "turbidity": 3.5, "temperature": null,
  "source": "ESP8266", "timestamp": "2026-10-30T14:02:11+00:00",
  "quality_score": 91.1,
  "score_method": "TWO_PARAM_SCREENING",
  "screening_status": "GOOD",
  "screening_explanation": "Preliminary screening score for TDS and turbidity is within the configured acceptable range.",
  "parameter_rule_check": {
    "label": "Parameter Rule Check",
    "status": "PASS",
    "parameters": {
      "tds": {"value": 250.0, "unit": "ppm", "status": "PASS", "detail": null},
      "turbidity": {"value": 3.5, "unit": "NTU", "status": "PASS", "detail": null}
    },
    "unavailable_parameters": [],
    "scope": "TDS and turbidity only",
    "disclaimer": "Passing this two-parameter check does NOT certify the water as potable or safe to drink. Laboratory testing is required."
  },
  "safety_status": "SAFE", "warning_message": null,
  "safety": {"status": "SAFE", "warning_message": null, "violated_parameters": []},
  "reading": {"id": 412, "device_id": "NODEMCU-001", "ph": null, "tds": 250.0, "turbidity": 3.5, "temperature": null, "source": "ESP8266", "timestamp": "2026-10-30T14:02:11+00:00", "quality_score": 91.1, "prediction": null, "confidence": null},
  "prediction": null, "confidence": null,
  "ml_status": "UNAVAILABLE", "ml_status_reason": "PH_NOT_MEASURED",
  "success": true
}
```

*(Note: `safety_status`/`safety` here are the deprecated compatibility mirrors — the assessment clients must display is `parameter_rule_check`.)*

Example — rule violations with score divergence (`S_tds(650)=72.0`, `S_turb(7.5)=70.8333` → 71.475 → **71.5** = GOOD; both parameters WARNING):

```json
"quality_score": 71.5, "screening_status": "GOOD",
"parameter_rule_check": {
  "label": "Parameter Rule Check", "status": "WARNING",
  "parameters": {
    "tds": {"value": 650.0, "unit": "ppm", "status": "WARNING", "detail": "TDS (650.0 ppm) is moderately above preferred threshold (500.0 ppm)"},
    "turbidity": {"value": 7.5, "unit": "NTU", "status": "WARNING", "detail": "Turbidity (7.5 NTU) is moderately above clarity threshold (5.0 NTU)"}
  },
  "unavailable_parameters": [], "scope": "TDS and turbidity only",
  "disclaimer": "Passing this two-parameter check does NOT certify the water as potable or safe to drink. Laboratory testing is required."
},
"safety_status": "WARNING"
```

Legacy 4-field payload (pH present) → same shape, but `ph`/`temperature` carry values, `ml_status: "AVAILABLE"` with populated `prediction`/`confidence`, and the Parameter Rule Check still evaluates **TDS + turbidity only**.

### 3.3 Read endpoints — historical vs new separation (P1 FINAL)

`GET /api/readings/latest` and `GET /api/readings/history` gain the additive optional fields `score_method`, `screening_status`, `parameter_rule_check`; `ph`/`temperature` become `Optional` (response-shape relaxation only — existing fields stay present, so the current frontend is not broken).

**Discriminator: `score_method`.**

| | **Historical record** (`score_method IS NULL`) | **New record** (`score_method = "TWO_PARAM_SCREENING"`) |
|---|---|---|
| `quality_score` | stored historical **four-parameter** score, returned as-is | two-parameter screening score |
| `score_method` | `null` (rendered by clients as FOUR_PARAM_LEGACY) | `"TWO_PARAM_SCREENING"` |
| `screening_status` | `null` — screening bands are **not applicable** to 4-param scores; never derived, never reconstructed | `GOOD`/`MODERATE`/`POOR`/`UNAVAILABLE` |
| `parameter_rule_check` | `null` — **no per-parameter rule results are fabricated or reconstructed for historical rows** | full `Parameter Rule Check` object (write-time result) |
| `safety_status` / `warning_message` | returned **verbatim with their original four-parameter meaning** — `SAFE`/`WARNING`/`UNSAFE` are NOT re-mapped to PASS/WARNING/FAIL and NOT re-interpreted | deprecated compatibility mirrors of the stored rule outcome (§3.2) |
| ML fields | as stored (`prediction`/`confidence` may be populated or null); no new claim is made | `prediction`/`confidence` null + `ml_status`/`ml_status_reason` when ML was skipped |

Example — historical row as returned by `GET /api/readings/history` (illustrative values):

```json
{
  "id": 17, "device_id": "SIMULATOR-001",
  "ph": 7.1, "tds": 240.0, "turbidity": 1.8, "temperature": 25.0,
  "source": "SIMULATION", "timestamp": "2026-10-28T09:15:00+00:00",
  "quality_score": 84.6,
  "score_method": null,
  "screening_status": null,
  "parameter_rule_check": null,
  "safety_status": "UNSAFE",
  "warning_message": "pH (5.10) is severely acidic (threshold min: 6.50)",
  "prediction": null, "confidence": null
}
```

**Unavailable-field representation (explicit contract):**
- *Unavailable new assessment* (required measurement missing/invalid — defensively only, since `tds`/`turbidity` are 422-required): `quality_score: null` + `screening_status: "UNAVAILABLE"` + `parameter_rule_check` marking that parameter `UNAVAILABLE` (overall per §5 ordering); the row still carries `score_method: "TWO_PARAM_SCREENING"`.
- *Unavailable historical assessment fields*: represented as **explicit `null`** (`screening_status`, `parameter_rule_check`) together with `score_method: null` — the `score_method` discriminator tells clients these are "not applicable/not recorded", **not** "failed" and **not** "PASS". Historical `safety_status`/`warning_message` are returned as stored, never completed from partial data.
- *Unavailable ML verdict*: `prediction: null` + `confidence: null` + `ml_status: "UNAVAILABLE"` + reason (§6) — never rendered as `NOT POTABLE`.

`GET /api/predictions/latest`: unchanged logic (already filters `prediction IS NOT NULL`); 404 when every recent row has NULL predictions.

### 3.4 New endpoints (D6) — device **connectivity only** (not sensor health)

- `GET /api/devices` → `List[DeviceResponse]` with `status` computed live from telemetry recency: **ONLINE** = telemetry received within `Settings.DEVICE_OFFLINE_THRESHOLD_SECONDS` (30 s); **OFFLINE** = no telemetry within the threshold (stored `status` column refreshed opportunistically).
- `GET /api/devices/{device_id}` → `DeviceResponse`, 404 when unknown.
- `DeviceResponse.source` gains `"ESP8266"`.
- **This status measures device connectivity ONLY.** The device API exposes **no sensor-health claim**: TDS/turbidity sensor health is **UNKNOWN** unless actual sensor diagnostics or validated sensor-health evidence become available. Sensors must **not** be displayed as WORKING solely because recent telemetry was received, and health must **not** be inferred from a plausible numeric reading. (No new hardware diagnostics or firmware requirements are introduced in Phase 10.)
- `GET /api/statistics`: **deferred** (D6).

### 3.5 Config contract — `GET /api/config` / `PUT /api/config`

Both endpoints gain the two band fields (B1 final), alongside the six legacy thresholds (values preserved):

```json
{
  "id": 1,
  "ph_min": 6.5, "ph_max": 8.5,
  "tds_max": 500.0, "turbidity_max": 5.0,
  "temperature_min": 10.0, "temperature_max": 35.0,
  "status_good_min": 70.0,
  "status_poor_max": 40.0,
  "updated_at": "2026-10-30T14:00:00+00:00"
}
```

- Defaults preserved: **GOOD ≥ `status_good_min` (70.0), POOR < `status_poor_max` (40.0)**; MODERATE in between.
- Validation: both must satisfy `0 ≤ value ≤ 100` and **`status_poor_max` strictly less than `status_good_min` → otherwise HTTP 400**.
- Legacy pH/temperature keys remain present (values preserved by the migration) and optional to send.

---

## 4. Quality Assessment Plan (Task 3)

New function in `backend/app/services/quality_service.py` (the legacy 4-parameter function stays untouched):

```python
WEIGHT_TDS = 0.55
WEIGHT_TURBIDITY = 0.45

@dataclass
class ScreeningScoreResult:
    overall_score: Optional[float]          # None -> UNAVAILABLE
    sub_scores: Dict[str, float]            # "tds", "turbidity" (rounded for display)
    weights: Dict[str, float]               # {"tds": 0.55, "turbidity": 0.45}
    screening_status: str                   # GOOD | MODERATE | POOR | UNAVAILABLE
    screening_explanation: Optional[str]
    unavailable_reason: Optional[str]       # e.g. "TDS_NOT_MEASURED"

def calculate_screening_score(tds: Optional[float], turbidity: Optional[float],
                              config: SystemConfig) -> ScreeningScoreResult: ...
def classify_screening_status(score: Optional[float], config: SystemConfig) -> str: ...
```

Rules:
- Formula: `round((S_tds × 0.55) + (S_turbidity × 0.45), 1)`, clamped [0, 100]; **only the final score is rounded** (intermediate sub-indices at full precision). Sub-index curves copied verbatim from the existing TDS/turbidity blocks (design §3.1/§3.2). TDS contributes 55%, turbidity 45%.
- `None`/non-finite/invalid `tds` **or** `turbidity` → `overall_score = None`, `screening_status = "UNAVAILABLE"`, `unavailable_reason` set; **no partial score is ever computed**; no value is defaulted or fabricated.
- **Configurable bands — final decision B1 (database-backed):**
  - `GOOD` if score ≥ `config.status_good_min` (default **70.0**); `MODERATE` if `config.status_poor_max ≤ score < status_good_min` (default ≥ 40.0); `POOR` if score < `config.status_poor_max` (default **40.0**); `UNAVAILABLE` if score is `None`.
  - The two columns are part of the **planned migration** (§7.2), the SQLAlchemy `SystemConfig` model, the Pydantic `SystemConfigBase/Update/Response` schemas, and `config_service` validation (`status_poor_max < status_good_min`, else HTTP 400) — both exposed through `GET/PUT /api/config` (§3.5).
  - Existing `system_config` row `id=1` receives the defaults **70.0 / 40.0** via the column `DEFAULT`s **without losing any existing values**.
  - `UNAVAILABLE` is never coerced into a scored band.
- Disclaimer text retained in module docstring and surfaced via `screening_explanation` — **neither GOOD nor PASS may be described as "safe to drink" or certified; laboratory testing is required.**
- Storage: `predictions.score_method = "TWO_PARAM_SCREENING"` for every row written by the new pipeline (including pH-bearing legacy-style payloads); historical rows keep `NULL` and are **never backfilled or updated** (R-3). Historical rows receive `screening_status = null` on read — the two score generations are never averaged or compared (§3.3).
- Verified examples 91.1 and 71.5 become acceptance tests (§9, T1/T2/T18).

---

## 5. Parameter Rule Check Plan

New function in `backend/app/services/safety_service.py` (legacy `evaluate_safety` untouched):

```python
@dataclass
class ParameterRuleResult:
    name: str                    # "tds" | "turbidity"
    value: Optional[float]
    unit: str                    # "ppm" | "NTU"
    status: str                  # PASS | WARNING | FAIL | UNAVAILABLE
    detail: Optional[str]

@dataclass
class ParameterRuleCheckResult:
    status: str                  # overall: PASS | WARNING | FAIL | UNAVAILABLE
    parameters: List[ParameterRuleResult]
    unavailable_parameters: List[str]
    warning_message: Optional[str]      # joined details (persisted, as today)
    storage_status: SafetyStatus        # new rows only: persistence mirror (see P1)

def evaluate_parameter_rule_check(tds: Optional[float], turbidity: Optional[float],
                                  config: SystemConfig) -> ParameterRuleCheckResult: ...
```

Bands (reuse existing thresholds, unchanged logic):
- TDS: PASS ≤ `tds_max`; WARNING ≤ `tds_max × 1.5`; FAIL > `tds_max × 1.5`.
- Turbidity: PASS ≤ `turbidity_max`; WARNING ≤ `turbidity_max × 2.0`; FAIL > `turbidity_max × 2.0`.
- Missing/invalid value → that parameter `UNAVAILABLE` (**never PASS**), with detail "not measured".

Overall aggregation: worst-of, ordered **`FAIL > WARNING > UNAVAILABLE > PASS`** (problem evidence is never masked by missing data; an incomplete check can never read PASS).

**Display terminology & historical separation (P1 FINAL):**
- The display name is **"Parameter Rule Check"** with `PASS`/`WARNING`/`FAIL` (+ `UNAVAILABLE`); `SAFE`/`UNSAFE` are **not** used as new-record display labels.
- The check applies **only to new two-sensor records**. Historical records keep their stored four-parameter `safety_status`/`warning_message` with their original meaning — they are **not** re-interpreted as PASS/FAIL, not re-evaluated, and **no per-parameter historical results are fabricated or reconstructed** (`parameter_rule_check: null` on read, §3.3).
- For new records, `storage_status` (PASS→`SafetyStatus.SAFE`, WARNING→`WARNING`, FAIL→`UNSAFE`, overall-UNAVAILABLE→`WARNING` defensive-only) exists **solely** to satisfy the NOT NULL `predictions.safety_status` column; API consumers read `parameter_rule_check`. Rows are distinguished by `score_method`.
- The screening score and the Parameter Rule Check remain **two separate outputs**, both always returned for new records; neither `GOOD` nor `PASS` certifies drinking-water safety — laboratory testing is required.

---

## 6. ML Compatibility Plan (Task 4)

Changes confined to `reading_service.py` (guard) + response assembly; **`app/ml/service.py` and the joblib artifact are not modified or retrained.**

- In `create_reading_with_assessment`, replace the unconditional call:
  - `if db_reading.ph is None:` → `ml_result = None`, `ml_status = "UNAVAILABLE"`, `ml_status_reason = "PH_NOT_MEASURED"` — **the model is never invoked, never fed a fake pH**.
  - `else:` → existing `ml_service.predict_reading(ph=..., tds=..., turbidity=...)` inside the current `try/except`; on `None` return → `ml_status = "UNAVAILABLE"` with reason `MODEL_UNAVAILABLE`/`INFERENCE_FAILED` (distinguish via `get_ml_service().last_error`).
- Persistence unchanged: ML ran → `predictions.prediction`/`confidence` stored; skipped/failed → both `NULL`.
- **Unavailable vs negative prediction (explicit contract):**

| Case | `prediction` | `confidence` | `ml_status` | `ml_status_reason` |
|---|---|---|---|---|
| pH missing (new hardware) | `null` | `null` | `UNAVAILABLE` | `PH_NOT_MEASURED` |
| Model failed/unavailable | `null` | `null` | `UNAVAILABLE` | `MODEL_UNAVAILABLE` / `INFERENCE_FAILED` |
| pH present, model says not potable | `"NOT POTABLE"` | probability (0–1] | `AVAILABLE` | `null` |

  A `NULL` prediction **never** means "NOT POTABLE" — it means the model did not produce a verdict. `GET /api/predictions/latest` already filters `prediction IS NOT NULL`, so unavailable rows cannot surface as verdicts.
- Legacy path preserved: any payload carrying pH (simulator, ESP32) goes through the exact same inference + persistence path as today.

---

## 7. Database Compatibility Plan (Task 5) — prepared separately from code

**The migration is a hard prerequisite for persisting NULL pH/temperature against MySQL:** `app/main.py::Base.metadata.create_all` only *creates missing tables* — it never alters existing ones — so after the ORM change the live table would still reject `NULL` (MySQL error 1048) until the draft is applied. The same applies to the **required `score_method` column** (R-3) and the **required `status_good_min`/`status_poor_max` columns** (B1): code selecting/writing missing columns fails (MySQL 1054 unknown column) → migration must be executed **before** backend code relying on these columns is deployed. Nothing below has been executed; no MySQL connection was made while writing this plan, and `database/schema.sql` is treated as a **reference baseline, not as proof of the live schema**. **The live database schema has not been verified.**

### 7.1 Backend dependencies on the proposed schema changes

| Proposed schema change | Backend dependency it unblocks | Consequence if code ships first |
|---|---|---|
| `water_readings.ph/temperature` → NULL | `WaterReading.ph/.temperature = None` on ESP8266 rows | INSERT fails → HTTP 500 |
| `water_readings.source` ENUM + `ESP8266` | `DeviceSource.ESP8266` inserts | MySQL 1265 "Data truncated" → HTTP 500 |
| `devices.source` ENUM + `ESP8266` | device upsert with ESP8266 source | MySQL 1265 → HTTP 500 |
| `system_config` pH/temp columns → NULL (values preserved) | optional legacy config fields (`SystemConfigUpdate` already optional) | only blocks *future* clearing of those keys; GET/PUT keep working with stored values |
| **`predictions.score_method` — REQUIRED (R-3 final)** | `Prediction.score_method`; `score_method` discriminator in every read response (§3.3) | MySQL 1054 on SELECT/INSERT → HTTP 500; historical/new separation impossible |
| **`system_config.status_good_min` / `status_poor_max` — REQUIRED (B1 final)** | configurable GOOD ≥ 70 / POOR < 40 bands via `GET/PUT /api/config`; `classify_screening_status` | MySQL 1054 on config SELECT → config endpoints fail; screening classification cannot run |

### 7.2 Final decisions applied to the migration plan *(draft SQL file amended in Phase 10 Step 4 — still NOT executed)*

- **R-2 = B1 (FINAL): database-backed band thresholds.** The amended draft now contains (as Section 4B, with an `information_schema.COLUMNS` re-run guard):

  ```sql
  -- ADDED TO THE DRAFT in Phase 10 Step 4 as Section 4B of database/migrations/phase9_scope_reconciliation.sql (still NOT executed)
  ALTER TABLE system_config
      ADD COLUMN status_good_min FLOAT NOT NULL DEFAULT 70.0,
      ADD COLUMN status_poor_max FLOAT NOT NULL DEFAULT 40.0;
  ```

  Backward compatible: the existing row `id=1` receives **70.0 / 40.0** through the column `DEFAULT`s, preserving all existing threshold values (pH/temp columns keep their values, merely becoming NULLable). Both columns appear in the SQLAlchemy model, the Pydantic schemas, `config_service` validation, `GET/PUT /api/config` and the test plan.
- **R-3 = REQUIRED (FINAL): `score_method` is a mandatory migration step.** The column is in the draft as Section 4 (promoted from OPTIONAL to REQUIRED; `information_schema.COLUMNS` re-run guard; still NOT executed):

  ```sql
  -- In the draft as Section 4 (promoted from OPTIONAL to REQUIRED; still NOT executed)
  ALTER TABLE predictions
      ADD COLUMN score_method ENUM('FOUR_PARAM_LEGACY','TWO_PARAM_SCREENING') NULL DEFAULT NULL
      AFTER quality_score;
  ```

  New assessment records store `TWO_PARAM_SCREENING`; historical records retain `NULL`; **historical records are never backfilled or updated**; the column **must be present before backend code relying on it is deployed**.
- **Model parity (Phase 10 Step 4): `idx_score_method` index.** `Prediction.score_method` is declared `index=True` in the SQLAlchemy model; the amended draft adds the matching index (as Section 4C, guarded by `information_schema.STATISTICS`):

  ```sql
  -- ADDED TO THE DRAFT in Phase 10 Step 4 as Section 4C (still NOT executed)
  ALTER TABLE predictions
      ADD INDEX idx_score_method (score_method);
  ```
- **Preservation rules (unchanged):** no `UPDATE`/`DELETE` of historical records; historical pH/temperature values preserved (made nullable, never dropped); `SIMULATION` and `ESP32` remain valid enum members; `ESP8266` is **added** without removing legacy members (widening only).

### 7.3 Exact schema details to verify before any migration (read-only, DBA run) — MANDATORY

Against the live `water_quality_db` (via `information_schema` or a scratch `mysqldump`), **not** against `schema.sql` — the live schema has never been verified:

1. `water_readings`: `ph`, `temperature`, `tds`, `turbidity` — actual `DATA_TYPE` (`FLOAT` expected), `IS_NULLABLE` (`ph`/`temperature` = `NO` pre-migration), `COLUMN_COMMENT`, `COLUMN_TYPE` of `source` (must contain exactly members `SIMULATION`,`ESP32` pre-migration), plus actual row count.
2. `devices`: `source` `COLUMN_TYPE` members; row count; the `SIMULATOR-001` seed row.
3. `predictions`: `quality_score` `IS_NULLABLE` (`NO` expected), `safety_status` members (`SAFE`,`WARNING`,`UNSAFE`), `prediction` members (`POTABLE`,`NOT POTABLE`), **existence of `score_method`** (expect absent → required addition), row count.
4. `system_config`: eight columns expected after migration — six legacy thresholds' `DATA_TYPE`/`IS_NULLABLE` (expect `NO` pre-migration), **existence of `status_good_min`/`status_poor_max`** (expect absent → required B1 addition), row `id=1` values (must be preserved).
5. Indexes/constraints: `fk_readings_device`, `fk_prediction_reading`, `CHECK (id = 1)` on `system_config`, enum defaults.
6. **Drift check:** compare the live schema with `database/schema.sql` (any divergence stops the migration until reconciled).
7. MySQL version (determines `ADD COLUMN IF NOT EXISTS` availability and enum-modify algorithm) + table sizes (rebuild/lock estimate).

### 7.4 Backup and restoration checks (before execution) — MANDATORY

1. **Full backup:** `mysqldump water_quality_db` to a dated file; record row counts of all four tables.
2. **Restore the backup into a staging database** and re-run the read-only verification (§7.3) against it — proof the backup is actually restorable.
3. **Rehearse the migration and the rollback** (§7.5) on the restored copy, including the planned §7.2 additions; record timings for the enum/column `ALTER`s.
4. Keep the dump until the post-migration acceptance checks (§7.6) are signed off; never run DDL without a verified backup.

### 7.5 Rollback considerations

- MySQL DDL auto-commits: **no transactional undo** — rollback = restore-from-dump, or guarded reverse-ALTERs.
- Reverse `ph`/`temperature` → `NOT NULL` **only while no NULL rows exist** (pre-hardware-data state); reverse source enums to `('SIMULATION','ESP32')` **only while no `ESP8266` rows exist** (draft already encodes both guards) — `SIMULATION`/`ESP32` remain valid at every point.
- `score_method`: drop only if `COUNT(score_method IS NOT NULL) = 0` (i.e. before any new pipeline writes) — historical rows are otherwise never touched.
- `status_good_min`/`status_poor_max`: drop only while every value equals its default (70.0 / 40.0) — never silently discard customized configuration values (guard encoded in the draft's Section 6).
- `idx_score_method`: index-only; may be dropped independently of any column rollback (no data attached).
- **Rule:** never rollback over data — if hardware rows already exist, restore the dump or leave the widened schema in place.

### 7.6 Post-execution acceptance checks (read-only) — MANDATORY

Row counts identical to pre-migration; **historical values verified**: sample legacy row's `ph`/`temperature` byte-identical; historical `predictions.score_method` **all NULL** (no backfill); `SHOW COLUMNS` reflects NULL + widened enums + `score_method` present + `status_good_min`/`status_poor_max` present with defaults 70.0/40.0 on row `id=1` (existing config values unchanged); `SELECT source, COUNT(*) GROUP BY source` unchanged for historical values (`SIMULATION`, `ESP32` intact).

### 7.7 Separation of workstreams (hard boundary)

| **A. Backend code implementation** — Steps **1–10** of §8 (gated by Gate 2) | **B. DB migration preparation & execution** — Step 0 + migration sequence (gated by Gate 3, **separate & explicit**) |
|---|---|
| Step 1 Model changes · Step 2 Schema changes · Step 3 Configuration compatibility · Step 4 Quality assessment service · Step 5 Parameter Rule Check service · Step 6 Reading persistence and validation · Step 7 Conditional ML inference · Step 8 Device API · **Step 9 Response compatibility and router wiring** · Step 10 Backend test updates | 1. Verify live schema (§7.3) · 2. Full backup + restore into staging (§7.4) · 3. Rehearse migration + rollback · 4. Prepare draft amendments (§7.2: band columns + score_method required) · 5. **Explicit approval** · 6. Execute draft · 7. Post-migration checks (§7.6) |
| Verified against in-memory SQLite unit fixtures; MySQL integration only after Gate 3 | Runs **before** any ESP8266 payload is sent to MySQL; deployment order = migration first, then code (or same window, migration before restart) |

**No database operation of any kind belongs in Gate 2. Database execution remains separately gated by explicit approval.**

---

## 8. Ordered Implementation Plan (Task 6)

> Order shown = recommended execution sequence. **Nothing in this section has been implemented.**
> **Workstream A (Gate 2) = Steps 1–10 (includes Step 9).** **Workstream B (Gate 3, separately gated) = Step 0 + the migration sequence §7.3–7.6.** **Step 11 = regression testing, after implementation and the separately approved migration.**

### Step 0 — Pre-implementation DB verification *(Workstream B / Gate 3, read-only)*
- **Files:** none created; results recorded in a checklist (e.g. `docs/PHASE_10_MIGRATION_VERIFICATION.md` — only if approved).
- **Functions:** n/a (DBA `information_schema` queries from §7.3).
- **Changes:** confirm §7.3 items; compare live schema with `database/schema.sql`; stop on drift.
- **Dependencies:** DB access approval. **Risks:** drift vs `schema.sql`; large-table ALTER locks.
- **Acceptance:** all verification items recorded; full backup taken and restored to staging; migration + rollback rehearsed (§7.4).

### Step 1 — Model changes *(Gate 2)*
- **Files:** `app/models/device.py`, `app/models/water_reading.py`, `app/models/prediction.py`, `app/models/system_config.py` (band columns — B1).
- **Classes:** `DeviceSource` (+`ESP8266 = "ESP8266"`), `WaterReading.ph`/`temperature` → `nullable=True`, new `ScoreMethod(str, enum.Enum)` (`FOUR_PARAM_LEGACY`, `TWO_PARAM_SCREENING`) and `Prediction.score_method` = `Column(Enum(ScoreMethod, values_callable=_enum_db_values), nullable=True, index=True)` after `quality_score`, `SystemConfig.status_good_min` (70.0) / `SystemConfig.status_poor_max` (40.0) — both `nullable=False` with defaults matching the migration columns.
- **Changes:** keep `prediction`/`confidence` nullable (as-is), `safety_status` non-null (persistence mirror for new rows only), no drops, no renames; add ORM comment "legacy column; NULL = not measured".
- **Dependencies:** Step 0 for MySQL reality; SQLite unit tests unaffected. **R-3 prerequisite:** the `score_method` and band columns **must exist in MySQL (Gate 3) before code touching them is deployed**.
- **Risks:** `create_all` does not alter existing tables (R-1); `Enum` mismatch with DB if migration unapplied.
- **Acceptance:** models import cleanly; SQLite `create_all` round-trips `ph=None` and both band columns with defaults 70.0/40.0; historical ORM reads unchanged; `score_method` default `NULL`.

### Step 2 — Schema changes (Pydantic) *(Gate 2)*
- **Files:** `app/schemas/water_reading.py`, `app/schemas/device.py`, `app/schemas/prediction.py`, `app/schemas/system_config.py` (band fields — B1), **new** `app/schemas/parameter_rule_check.py`.
- **Classes:** `WaterReadingBase` (ph/temperature `Optional`, source `+ESP8266`, bool-reject kept, `Optional` passes through), `WaterReadingResponse` (+`score_method`, `screening_status`, `parameter_rule_check`), `SafetyInfo` unchanged, `ReadingIngestionResponse` (per §3.2), `DeviceResponse.source` `+ESP8266`, `LatestPredictionResponse` untouched, new `ParameterRuleCheckParameter`/`ParameterRuleCheckInfo`, `SystemConfigBase/Response` + `status_good_min`/`status_poor_max`, `SystemConfigUpdate` + two optional band fields.
- **Dependencies:** Step 1 (enum parity). **Risks:** strictness regressions (booleans, ranges) — existing validators must keep firing.
- **Acceptance:** hardware payload validates without 422; missing `tds`/negative/`bool`/unknown `source` still 422; legacy 6-field payload validates; config schemas expose both band fields.

### Step 3 — Configuration compatibility *(Gate 2)*
- **Files:** `app/models/system_config.py`, `app/schemas/system_config.py`, `app/services/config_service.py`, `app/config.py`.
- **Classes:** `SystemConfig.ph_min/ph_max/temperature_min/temperature_max` → `nullable=True`; **(B1 FINAL)** add `status_good_min` (NOT NULL, default 70.0) / `status_poor_max` (NOT NULL, default 40.0) to the model; `SystemConfigBase/Response` legacy fields → `Optional[float]` + both band fields; `SystemConfigUpdate` + two optional band fields; `config_service.update_system_config` cross-field checks skip `None` comparisons for legacy pairs and add **`status_poor_max ≥ status_good_min` → HTTP 400**; `get_system_config` provisions band defaults when absent (provisioning fallback only — DB columns are authoritative).
- **Dependencies:** Step 1; migration (Gate 3) must add the band columns before deploy. **Risks:** provisioning path writes non-null defaults into now-nullable legacy columns (fine); cross-field check change breaks `test_config_update_changes_thresholds`.
- **Acceptance:** `GET /api/config` returns stored legacy values unchanged **plus `status_good_min=70.0`/`status_poor_max=40.0` (existing row gains defaults without losing values)**; partial `PUT` with only `tds_max` → 200, other values untouched; `PUT {status_poor_max: 75}` with `status_good_min=70` → 400; band update `PUT {status_good_min: 80}` → 200 and effective on the next assessment.

### Step 4 — Quality assessment service *(Gate 2)*
- **Files:** `app/services/quality_service.py` (+ tests later).
- **Classes/functions:** add `WEIGHT_TDS=0.55`, `WEIGHT_TURBIDITY=0.45`, `ScreeningScoreResult`, `calculate_screening_score(tds, turbidity, config)`, `classify_screening_status(score, config)` reading `config.status_good_min`/`config.status_poor_max`; keep `calculate_water_quality_score` and `QualityScoreBreakdown` untouched (historical path + 31 legacy service tests).
- **Dependencies:** Step 3 (band config). **Risks:** rounding order (sub-index full precision, round final only); Python banker's rounding on `77.75 → 77.8` — assert exact expected values.
- **Acceptance:** with default bands: 250/3.5 → **91.1 GOOD**; 650/7.5 → **71.5 GOOD**; 500/5.0 → 77.8; 900/12.0 → 60.8 MODERATE; 2000/50 → 0.0 POOR; `tds=None` → `None`/`UNAVAILABLE` (no partial score); weights sum to 1.00; with `status_good_min=80`, 71.5 → MODERATE (bands are truly configurable).

### Step 5 — Parameter Rule Check service *(Gate 2)*
- **Files:** `app/services/safety_service.py`.
- **Classes/functions:** add `ParameterRuleResult`, `ParameterRuleCheckResult`, `evaluate_parameter_rule_check(tds, turbidity, config)`; reuse existing 1.5×/2.0× bands; overall ordering `FAIL > WARNING > UNAVAILABLE > PASS`; `storage_status` mapping for **new rows only**. Keep `evaluate_safety` untouched (historical path).
- **Dependencies:** Step 3. **Risks:** accidental reordering of bands; exposing `SAFE/UNSAFE` as new-record display output (must not — P1); missing value slipping to PASS (explicit test required); reconstructing historical results (must not — P1).
- **Acceptance:** 250/3.5 → PASS/PASS overall PASS; 650/7.5 → WARNING/WARNING overall WARNING; 900/12 → FAIL/FAIL overall FAIL; `turbidity=None` → parameter UNAVAILABLE and overall **not PASS**; disclaimer present; no code path applies this check to historical rows.

### Step 6 — Reading persistence and validation *(Gate 2)*
- **Files:** `app/services/reading_service.py`.
- **Functions:** `create_reading_with_assessment` — conditional rounding (`round(float(v),2) if v is not None else None` for ph/temperature; tds/turbidity unchanged); call `calculate_screening_score` (Step 4) instead of the 4-param function; call `evaluate_parameter_rule_check` (Step 5) instead of `evaluate_safety`; construct `Prediction(quality_score=..., safety_status=result.storage_status, warning_message=..., score_method=ScoreMethod.TWO_PARAM_SCREENING, ...)`; keep device upsert (ESP8266 flows through widened enum) and commit/refresh structure; **no UPDATE/DELETE of existing rows, ever**.
- **Dependencies:** Steps 1, 4, 5. **Risks:** `None` reaching `round()` (TypeError → 500); tuple return type changes ripple into `routers/readings.py` (do together with Step 9); device `device_name` cosmetics for "Esp8266 Node".
- **Acceptance:** ESP8266 payload persists `ph=NULL`/`temperature=NULL` (post-migration integration) with `score_method=TWO_PARAM_SCREENING`; legacy 6-field payload persists with identical non-null legacy fields; historical rows untouched (checksums unchanged).

### Step 7 — Conditional ML inference *(Gate 2)*
- **Files:** `app/services/reading_service.py` (same function), response assembly in `app/routers/readings.py`.
- **Functions:** `ph is None → ml_result=None, ml_status=UNAVAILABLE, reason=PH_NOT_MEASURED` **before** any model call; else existing `ml_service.predict_reading(...)` in `try/except`; on `None` result derive `MODEL_UNAVAILABLE`/`INFERENCE_FAILED`.
- **Dependencies:** Step 6. **Risks:** calling the wrapper with `None` yields an unclassified `None` (must short-circuit first); `GET /api/predictions/latest` must keep returning only real verdicts.
- **Acceptance:** pH absent → `prediction=null`, `confidence=null`, `ml_status=UNAVAILABLE`, `ml_status_reason=PH_NOT_MEASURED`, artifact file byte-size/mtime unchanged; pH present → `AVAILABLE` with a verdict (or explicit failure reason); NULL never renders as "NOT POTABLE".

### Step 8 — Device API *(Gate 2)*
- **Files:** **new** `app/routers/devices.py`, **new** `app/services/device_service.py` (or functions in `reading_service` — recommend a small dedicated service), `app/main.py` (include router), `app/schemas/device.py` (Step 2).
- **Functions:** `list_devices(db)` (compute **connectivity** ONLINE/OFFLINE from `last_seen` vs `Settings.DEVICE_OFFLINE_THRESHOLD_SECONDS`), `get_device(db, device_id)` (404), `GET /api/devices`, `GET /api/devices/{device_id}`.
- **Scope:** **device connectivity only.** The endpoint returns **no sensor-health status**; sensor health is `UNKNOWN` without actual diagnostics or validated sensor-health evidence. No sensor may be reported as WORKING merely because telemetry arrived, and health must never be inferred from a plausible numeric reading. No firmware/diagnostics requirements are introduced here.
- **Dependencies:** Step 2. **Risks:** stored `status` vs computed status divergence; timezone-naive `last_seen` comparisons (mirror existing `timestamp` handling); **misreading connectivity as sensor health** (mitigated by scope statement + T24/T27 assertions).
- **Acceptance:** after an ESP8266 POST the device appears with `source=ESP8266`, connectivity ONLINE, `last_seen` fresh; `DEVICE_OFFLINE_THRESHOLD_SECONDS` honored (OFFLINE once stale); unknown id → 404; **no `WORKING`/`FAILED` sensor-health values anywhere in the device API response**; no statistics endpoint (D6).

### Step 9 — Response compatibility and router wiring *(final code step of Gate 2 — included in Workstream A)*
- **Files:** `app/routers/readings.py`, `app/routers/config.py` (band-field passthrough + docstrings), `app/schemas/*` (assembly), optionally `docs/api.md` (move proposal → "implemented" marker, only with approval).
- **Functions:** `create_reading_endpoint` builds `ReadingIngestionResponse` per §3.2 (new fields; `safety_status`/`safety` retained as deprecated mirrors); `WaterReadingResponse` additions for `/latest` + `/history` with the **P1 historical/new separation** (§3.3): `score_method` discriminator, explicit `null`s for inapplicable historical fields, verbatim legacy `safety_status`/`warning_message`.
- **Dependencies:** Steps 1–8; **P1 is FINAL** (no open decision remains for this step). **Risks:** response-field compatibility with the current frontend (additive only); accidentally re-mapping historical `SAFE/UNSAFE` → PASS/FAIL (explicitly forbidden, covered by T23).
- **Acceptance:** hardware POST → 201 with all §3.2 fields; historical row via GET shows `score_method=null`, `screening_status=null`, `parameter_rule_check=null`, original `safety_status`/`warning_message` untouched; new row shows `parameter_rule_check` as primary assessment; legacy payload structure unchanged; current React app still renders `/latest` and `/history`; 404/422/500 semantics unchanged.

### Step 10 — Backend test updates *(Gate 2 — see §9 matrix)*
- **Files:** `tests/test_readings_unit.py` (extend), `tests/test_phase3_api.py` (retarget pH/temp-driven safety assertions), `tests/test_phase5_ml_api.py` (retarget `test_temperature_unsafe_ml_potable_disagreement` etc.), **new** `tests/test_phase10_contract.py`; untouched: `test_phase3_services.py` (legacy functions kept), `test_simulator*.py`, `test_ml_pipeline.py`, `test_health.py`.
- **Acceptance:** matrix fully written as tests (results **not yet claimed**); every retarget documented.

### Step 11 — Regression testing *(after Gate 2 implementation AND the separately approved Gate 3 migration; results reported honestly)*
- Run unit suites first (`test_readings_unit`, `test_phase3_services`, `test_phase5_ml_api` unit subset) — SQLite-only; then MySQL-backed suites **after the approved migration**; then `test_simulator*` (unchanged contract) and full `pytest backend/tests`.
- **Acceptance:** all suites green; 119→(updated) inventory reconciled; manual `uvicorn` smoke of `/health`, `/docs`, one legacy payload and one hardware payload; ML artifact byte-size/mtime unchanged; no `requirements.txt` change; historical data checksums unchanged.

---

## 9. Test Strategy — Proposed Test Matrix (Task 7)

> **Proposed plan only — no tests were run and no test results are claimed.**

| # | Scenario | Layer | Fixture / method | Expected (planned assertions) |
|---|---|---|---|---|
| T1 | ESP8266 two-sensor payload `{device_id, tds:250.0, turbidity:3.5, source:"ESP8266"}` | API (SQLite unit) | `test_readings_unit` pattern | 201; `ph=null`, `temperature=null`; `quality_score=91.1`; `screening_status="GOOD"`; `parameter_rule_check.status="PASS"` (primary assessment); `score_method="TWO_PARAM_SCREENING"`; `source="ESP8266"`; `ml_status="UNAVAILABLE"` + `PH_NOT_MEASURED` |
| T2 | Score 71.5 case: tds 650 / turbidity 7.5 | Service unit | `calculate_screening_score` | `round(71.475,1)=71.5`, status `GOOD`; sub-indices 72.0 / 70.8333 |
| T3 | Parameter Rule Check **PASS** | Service unit | 250/3.5, defaults | both `PASS`, overall `PASS`, disclaimer present |
| T4 | Parameter Rule Check **WARNING** | Service unit | 650/7.5 | both `WARNING` (≤750 ppm, ≤10 NTU), overall `WARNING` |
| T5 | Parameter Rule Check **FAIL** | Service unit | 900/12.0 | both `FAIL` (>750, >10), overall `FAIL` |
| T6 | Missing measurement → never PASS | Service unit | `evaluate_parameter_rule_check(tds=None, turbidity=3.5, cfg)` | tds `UNAVAILABLE`, overall `UNAVAILABLE` (ordering: FAIL > WARNING > UNAVAILABLE > PASS) |
| T7 | Missing TDS in request | API | POST without `tds` | **422**, nothing persisted |
| T8 | Missing turbidity in request | API | POST without `turbidity` | **422** |
| T9 | Missing `device_id` / empty string | API | POST | **422** |
| T10 | Invalid values: negative tds, negative turbidity, `tds=true`, `ph=15`, `temperature=101`, non-numeric string | API | POST variants | **422** each; boolean never coerced to 1.0 |
| T11 | Invalid source `"ESP82"` | API | POST | **422** (Literal) |
| T12 | NULL pH/temperature persistence | Integration (post-migration) | POST + direct SELECT | column values are SQL `NULL` (not 0, not default) |
| T13 | Legacy 4-field SIMULATION payload (simulator exact 6-key shape) | API unit + integration | existing fixtures | 201; `ph`/`temperature` stored as sent; **historical rows' values unchanged** (pre/post row checksum) |
| T14 | Legacy ESP32 payload | API | `source="ESP32"` with pH | 201; source accepted; ML runs (pH present) |
| T15 | Conditional ML: pH absent | API | T1 payload | `prediction=null`, `confidence=null`, `ml_status="UNAVAILABLE"`, `ml_status_reason="PH_NOT_MEASURED"`; model never invoked (monkeypatch `ml_service.predict_reading` to raise/flag) |
| T16 | Conditional ML: pH present | API | 6-field payload | `ml_status="AVAILABLE"`, verdict or explicit failure reason; existing phase5 behavior intact |
| T17 | Unavailable vs negative prediction | API + service | pH absent **vs** model returns 0 | nulls + UNAVAILABLE ≠ `"NOT POTABLE"` + confidence; `GET /api/predictions/latest` excludes NULL rows (404 when only NULLs exist) |
| T18 | Score examples 91.1 / 71.5 exact | Service | §4 function | exact equality (documented verified vectors) |
| T19 | Band edges (defaults 70/40) | Service | 70.0→GOOD, 69.9→MODERATE, 40.0→MODERATE, 39.9→POOR, `None`→UNAVAILABLE | exact |
| T20 | Weights & range | Service | sum, clamp | `0.55+0.45=1.0`; score ∈ [0,100] at extremes (2000/50 → 0.0) |
| T21 | Config compatibility + band fields (B1) | API | `GET /api/config`; `PUT {tds_max: 400}`; `PUT {status_good_min: 80, status_poor_max: 50}`; `PUT {status_poor_max: 75}` with good=70 | GET returns `status_good_min=70.0`/`status_poor_max=40.0` with legacy values intact; PUTs → 200; `status_poor_max ≥ status_good_min` → **400** |
| T22 | DB error handling | API | monkeypatch `Session.commit` to raise | 500 "Failed to persist reading and evaluation"; no partial response |
| T23 | **Historical record compatibility (P1)** | SQLite/integration | seed legacy row (`ph=7.1`, 4-param score, `safety_status="UNSAFE"`, `warning_message`, `score_method IS NULL`) | `/history` returns it **unmodified**: `score_method=null`, `screening_status=null`, `parameter_rule_check=null` (nothing reconstructed), `safety_status`/`warning_message` **verbatim with original 4-param meaning — NOT mapped to PASS/WARNING/FAIL**; no UPDATE issued |
| T24 | Device API — **connectivity only** | API | after T1 → `GET /api/devices` | 200 list; ESP8266 connectivity ONLINE; `/NONEXIST` → 404; OFFLINE after threshold (frozen time / old `last_seen`); **no sensor-health/WORKING claims in the response** |
| T25 | Regression — untouched surfaces | Unit | `test_phase3_services.py`, `test_simulator.py`, `test_ml_pipeline.py`, `test_health.py` | still applicable as written (legacy functions retained; simulator contract unchanged) |
| T26 | **Band configurability affects classification (B1)** | Service/API | `PUT status_good_min=80` → reassess 71.5 score | reclassified `MODERATE`; revert to 70 → `GOOD` again |
| T27 | **New vs historical assessment separation (P1) + terminology** | API | one new ESP8266 row + one seeded historical row in the same `/history` response | new row: `parameter_rule_check` present with `PASS`/`WARNING`/`FAIL`/`UNAVAILABLE` vocabulary as primary, `screening_status` present; historical row: assessment nulls + legacy fields; **no legacy `SAFE/UNSAFE` label used as the primary assessment of a new record**; sensor health never asserted (UNKNOWN, no diagnostics) |
| T28 | **`score_method` column present (R-3 required) — migration** | Integration (post-migration, Gate 3) | `SHOW COLUMNS predictions LIKE 'score_method'` + `SELECT COUNT(*) WHERE score_method IS NOT NULL` | column exists (ENUM members as specified); all historical rows `NULL` (no backfill); new rows tagged `TWO_PARAM_SCREENING` |
| T29 | **Band columns present (B1) — migration** | Integration (post-migration, Gate 3) | `SHOW COLUMNS system_config LIKE 'status_good%'/'status_poor%'` + row `id=1` | columns exist with defaults 70.0/40.0; existing threshold values unchanged |

Retarget list (tests whose *premise* changes under the 2-parameter rule check — to be rewritten in Step 10, with reasons documented in the PR): `test_phase3_api.py::test_post_reading_abnormal_ph_warning`, `::test_post_reading_severely_acidic_unsafe`, `::test_post_reading_multiple_violations`, `::test_post_reading_high_turbidity_warning/unsafe` (band wording), `test_phase5_ml_api.py::test_temperature_unsafe_ml_potable_disagreement` (temperature no longer evaluated).

---

## 10. Exact File-Change Inventory (Task 8.4)

**Modify (runtime backend, Workstream A / Gate 2):**
1. `backend/app/models/device.py` — `DeviceSource` + ESP8266.
2. `backend/app/models/water_reading.py` — `ph`/`temperature` nullable.
3. `backend/app/models/prediction.py` — `ScoreMethod` enum + `score_method` column (requires Gate 3 migration first).
4. `backend/app/schemas/water_reading.py` — optional ph/temp, `+ESP8266`, new response fields.
5. `backend/app/schemas/device.py` — `+ESP8266`.
6. `backend/app/schemas/system_config.py` — optional legacy fields; **`status_good_min`/`status_poor_max` (B1, FINAL)**.
7. `backend/app/services/quality_service.py` — add 2-param screening score + band classification (legacy kept).
8. `backend/app/services/safety_service.py` — add Parameter Rule Check (legacy kept).
9. `backend/app/services/reading_service.py` — conditional persistence, new services, conditional ML, `score_method`.
10. `backend/app/services/config_service.py` — optional/cross-field band validation (`poor < good` → 400).
11. `backend/app/routers/readings.py` — response assembly, new fields, P1 historical/new separation.
12. `backend/app/main.py` — include `devices` router.
13. `backend/app/config.py` — band default constants only as provisioning fallback (DB columns authoritative per B1); reuse `DEVICE_OFFLINE_THRESHOLD_SECONDS` for connectivity.

**New (runtime backend, Workstream A / Gate 2):**
14. `backend/app/schemas/parameter_rule_check.py`.
15. `backend/app/routers/devices.py`.
16. `backend/app/services/device_service.py`.

**Tests (Workstream A):** modify `test_readings_unit.py`, `test_phase3_api.py`, `test_phase5_ml_api.py`; **new** `test_phase10_contract.py`; untouched: `test_phase3_services.py`, `test_simulator.py`, `test_simulator_integration.py`, `test_ml_pipeline.py`, `test_health.py`, `test_readings_integration.py` (+1 new ESP8266 case).

**Database (Workstream B — Gate 3, separately gated):** `database/migrations/phase9_scope_reconciliation.sql` — **amended in Phase 10 Step 4 (Sections 4B/4C: B1 band columns + `idx_score_method` index, both `information_schema`-guarded); still DRAFT / unexecuted — execution awaits Gate 3 explicit approval**; `database/schema.sql` (sync *after* migration approval); optional `docs/PHASE_10_MIGRATION_VERIFICATION.md`.

**Explicitly untouched:** `backend/app/ml/service.py`, `ml/**` (artifact + metrics), frontend `frontend/src/**`, `simulator/**`, `firmware/**`, `backend/requirements.txt`, `backend/tests/test_simulator*.py`, all migration SQL (in this task).

---

## 11. Risks and Unresolved Issues (Task 8.9)

| ID | Risk / issue | Impact | Mitigation / status |
|---|---|---|---|
| R-1 | `Base.metadata.create_all` never alters existing MySQL tables → ORM-vs-schema mismatch until migration runs (missing `ph`/`temperature` NULLability, `ESP8266` enum member, `score_method`, `status_good_min`/`status_poor_max`) | INSERT/SELECT failures → HTTP 500 (MySQL 1048/1265/1054) | Deployment order: **migration (Gate 3) before code**, or same window migration-first; unit tests unaffected (SQLite) |
| R-2 | ~~Band thresholds exist nowhere~~ **RESOLVED — R-2 = B1 (FINAL):** DB-backed `status_good_min`/`status_poor_max` (defaults 70.0/40.0) added to model, schemas, `config_service`, `GET/PUT /api/config` and the migration plan (§7.2) | remaining: migration draft amendment + execution | Draft amendment prepared at Gate 3 (SQL **not** edited in this task); execution separately approved |
| R-3 | ~~`score_method` optional~~ **RESOLVED — R-3 = REQUIRED (FINAL):** mandatory migration step; `TWO_PARAM_SCREENING` for new rows; historical rows stay `NULL`, never backfilled; column required **before** relying code deploys | remaining: migration draft amendment + execution | Same Gate 3 treatment as R-2; read-time inference is **no longer** the plan |
| R-4 | ~~P1 unresolved~~ **RESOLVED — P1 = SEPARATE (FINAL):** historical records keep original 4-param meaning (`safety_status`/`warning_message` verbatim; `screening_status`/`parameter_rule_check` = explicit `null`; nothing reconstructed); new records use Parameter Rule Check as primary; discriminator = `score_method` (§3.3) | residual: clients must honor `score_method` (documented; T23/T27) | No open contract decision remains for read endpoints |
| R-5 | pH/temperature-based API tests (phase3/phase5) will legitimately fail after the rule check changes scope | CI red if retarget missed | Explicit retarget list in §9; keep 4-param service tests green as the safety net |
| R-6 | `predictions.quality_score` stays NOT NULL | Blocks a future "missing tds" 201 path (turbidity-only rows) | Out of scope: tds/turbidity remain required (422) → score always computable; a defensive UNAVAILABLE response path exists for reads; revisit only with a new approved contract |
| R-7 | Live schema drift vs `database/schema.sql` unknown (never connected) | Migration could assume wrong column types | Gate 3 §7.3 mandatory verification stops on drift |
| R-8 | Enum/table rebuild locks during ALTER on a live DB | Write downtime | §7.4 staging timing + maintenance window |
| R-9 | Stored `safety_status` mirror could be mistaken for the primary assessment of a new record | Consumers displaying deprecated labels | P1 final: `parameter_rule_check` documented as primary (§3.2); mirrors labelled DEPRECATED; historical rows never mapped; T23/T27 enforce |
| R-10 | `device.status` stored vs computed ONLINE/OFFLINE can diverge; `last_seen` is timezone-naive | Wrong connectivity badge | Compute at read time from `last_seen` (Phase 9 design F4); scope labelled **connectivity only** |
| R-11 | P2 (admin auth) and P3 (simulator flag naming) still pending | Config PUT remains unauthenticated | Explicitly out of Phase 10 scope; P2 required before deployment |
| R-12 | Simulator still sends 6-field 4-channel payloads until Phase 12 | Legacy payloads keep flowing (accepted by design) | No action in Phase 10; contract must remain backward compatible (T13) |
| R-13 | **Sensor health cannot be determined from telemetry** — no diagnostics exist for TDS/turbidity sensors | Displaying sensors as "WORKING" because data arrives (or from plausible values) would be a false safety signal | Sensor health = **UNKNOWN** by default; device API exposes connectivity only (§3.4, Step 8); no firmware/diagnostics introduced in Phase 10; T24/T27 assert absence of health claims |

---

## 12. Approval Gates (Task 8.10)

- **Gate 1 — Plan review (current):** you review this corrected document; explicit approval required before *any* code file is touched.
- **Gate 2 — Backend code implementation (Workstream A): covers Steps 1–10 — including Step 9 (response compatibility and router wiring):** models (Step 1), schemas (Step 2), configuration compatibility (Step 3), quality assessment service (Step 4), Parameter Rule Check service (Step 5), reading persistence and validation (Step 6), conditional ML inference (Step 7), device API (Step 8), response compatibility and router wiring (Step 9), backend test updates (Step 10). Verified against in-memory SQLite only. **No database operation belongs in Gate 2.**
- **Gate 3 — Database migration (Workstream B, separate & explicit):** database verification (§7.3) → full backup → restore into staging → rehearse migration and rollback → migration preparation (draft amendment per final decisions B1 + R-3) → **explicit separate approval** → execution → post-migration checks (§7.6). *Database execution remains separately gated by explicit approval.*
- **Gate 4 — Full regression + MySQL integration run (Step 11):** executed after Gates 2 and 3; results reported honestly (no claims beforehand).
- **Gate 5 — Phase 11 start:** requires your explicit approval after Gate 4 review.
- **Remaining pending decisions:** **P2** (admin authentication mechanism) and **P3** (simulator legacy-mode flag naming) — see roadmap §5. *R-2, R-3 and P1 are FINAL and are no longer open.*

---

- Phase 10 planning corrections: COMPLETED.
- Backend runtime code modified: NO.
- Migration SQL modified: NO.
- Database migration executed: NO.
- Database records modified: NO.
- ML model retrained: NO.
- Frontend/simulator/firmware modified: NO.
- Phase 11 started: NO.
- Backend implementation: AWAITING EXPLICIT APPROVAL.
- Database migration execution: AWAITING SEPARATE EXPLICIT APPROVAL.
