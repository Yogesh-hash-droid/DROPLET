# Phase 9 — Implementation Roadmap (for Phases 10+)

> **Status:** PLAN — **no implementation was started in Phase 9.**
> **Input:** `PROJECT_AUDIT_REPORT.md` (§4 Required Corrections, §5 Plan) + Phase 9 design documents.
> **Scope of future work:** ESP8266 NodeMCU + ADS1115 + TDS + Turbidity, two-parameter assessment, redesigned dashboard.

---

## 1. Files Requiring Changes (complete inventory)

### 1.1 Backend — required changes

| File | Why | Phase |
|---|---|---|
| `backend/app/schemas/water_reading.py` | `ph`/`temperature` → optional (`None`); add `source: "ESP8266"`; keep bool-rejection validators | 10 |
| `backend/app/schemas/system_config.py` | pH/temperature thresholds → optional; add `status_good_min`/`status_poor_max` | 10 |
| `backend/app/schemas/prediction.py` | add `score_method` / `screening_status` / `parameter_rule_check` / `ml_status` / `ml_status_reason` fields (optional) | 10 |
| `backend/app/schemas/device.py` | `source` literal → include `ESP8266` | 10 |
| `backend/app/models/device.py` | `DeviceSource` add `ESP8266` (keep `ESP32` for legacy rows) | 10 |
| `backend/app/models/water_reading.py` | `ph`/`temperature` nullable | 10 |
| `backend/app/models/system_config.py` | pH/temperature thresholds nullable; new status-band columns | 10 |
| `backend/app/models/prediction.py` | optional `score_method` column | 10 |
| `backend/app/services/safety_service.py` | 2-parameter Parameter Rule Check (`PASS`/`WARNING`/`FAIL`); skip missing parameters (never treat missing as `PASS`) | 10 |
| `backend/app/services/quality_service.py` | 2-parameter score, weights 0.55/0.45, `score_method` tag; refuse to score missing inputs | 10 |
| `backend/app/services/reading_service.py` | store `NULL` pH/temp, run ML only when `ph` present, tag score method, set ML status | 10 |
| `backend/app/services/config_service.py` | drop pH/temp cross-field rules; add status-band validation; optional legacy keys | 10 |
| `backend/app/config.py` | remove/retire pH+temperature defaults; add band defaults | 10 |
| `backend/app/ml/service.py` | **artifact untouched**; skip inference when `ph` missing (explicit `ML_UNAVAILABLE_PH_MISSING`) | 10 |
| `backend/app/routers/readings.py` | echo `score_method`, `ml_status`; (recommended) add `violated_parameters` to `/latest` | 10 |
| `backend/app/routers/config.py` | unchanged routes; new optional fields flow through | 10 |
| `backend/app/routers/devices.py` | **new file** — `GET /api/devices`, `GET /api/devices/{id}` | 10 |
| `backend/app/routers/statistics.py` | **new file** — `GET /api/statistics` (optional, dashboard Analytics) | 10/15 |
| `backend/app/main.py` | register new routers; log `create_all()` failures instead of `pass` | 10 |
| `database/schema.sql` | sync DDL with the migration (nullable pH/temp, new enum, band columns) | 10 |
| `database/migrations/phase9_scope_reconciliation.sql` | **execute only after approval** (draft exists) | 10 |

### 1.2 Backend — tests (near-total rewrite)

| File | Impact |
|---|---|
| `tests/test_phase3_services.py` | **All 31 tests** — 4-arg positional calls → 2-param; band/score assertions rewritten |
| `tests/test_phase3_api.py` | 12 tests — pH/temp scenarios, config cross-field tests |
| `tests/test_readings_unit.py` | payload shape, pH validation cases (become legacy/optional cases) |
| `tests/test_readings_integration.py` | MySQL payloads + `ph` assertions |
| `tests/test_phase5_ml_api.py` | 14 tests — helper payloads; pH-missing → NULL becomes the **new core case** |
| `tests/test_simulator.py` | 27 tests — exact 6-key payload contract → hardware-shaped contract |
| `tests/test_simulator_integration.py` | live payloads |
| `tests/test_ml_pipeline.py` | largely unchanged (artifact still 3-feature) — keep as regression |
| `tests/test_health.py` | unchanged (2 tests) |
| **New tests required** | 2-param safety bands · missing-parameter handling · score `score_method` tagging · ML-unavailable (≠ NOT POTABLE) · `ESP8266` source acceptance · device endpoints · config bands · 422 validation matrix |

### 1.3 Simulator

| File | Change | Phase |
|---|---|---|
| `simulator/sensors.py` | hardware-shaped 2-channel mode (pH/temp channels retired or made opt-in) | 12 |
| `simulator/scenarios.py` | retire/rework `PH_DRIFT_*`, `ACIDIC`, `ALKALINE`, `TEMPERATURE_SPIKE`; keep TDS/turbidity scenarios | 12 |
| `simulator/client.py` | payload builder without pH/temp; `source` selection rules | 12 |
| `simulator/simulator.py` | CLI flags/output columns (drop PH/TEMP columns) | 12 |
| `simulator/README.md` | contract documentation | 12 |

### 1.4 Frontend

| File | Change | Phase |
|---|---|---|
| `src/utils/constants.js` | `PARAMS` → 2 entries; status bands; disclaimers | 13 |
| `src/utils/thresholds.js` | 2-parameter mirror only | 13 |
| `src/utils/screeningScore.js` | **new** — score mirror (display only) | 13 |
| `src/utils/exportCsv.js` | **new** — CSV export | 13 |
| `src/pages/Dashboard.jsx` | 2 cards, screening status, device/sensor status, staleness | 13 |
| `src/pages/History.jsx` | new columns/filters, no pH/temp | 13 |
| `src/pages/Analytics.jsx` | **new** page | 13 |
| `src/pages/Reports.jsx` | **new** page | 13 |
| `src/pages/Settings.jsx` | 2 thresholds + bands; devices panel; ML note | 13 |
| `src/components/ThresholdSettingsForm.jsx` | remove 4 legacy fields; add band fields | 13 |
| `src/components/SensorCard.jsx`, `TrendChart.jsx`, `HistoryTable.jsx`, `ScoreGauge.jsx` | parameter-driven adjustments | 13 |
| `src/components/MLVerdictCard.jsx` | "ML unavailable (pH not measured)" state distinct from NOT POTABLE | 13 |
| `src/components/Header.jsx`, `src/App.jsx`, `src/styles.css` | ESP8266 labels, nav (5 tabs), connection indicator | 13 |
| `src/services/api.js` | devices endpoint, export helper | 13 |
| `src/test/fixtures/*.json` | regenerate 2-sensor payloads; remove mojibake | 13 |
| `src/**/*.test.*` | update + add absence-of-pH/temperature assertions | 13 |
| `docs/…`, `README.md`, `PROJECT_STATUS.md` | counts, scope wording | 13/15 |

### 1.5 Firmware & hardware (new)

| Item | Phase |
|---|---|
| `esp8266/` directory (replaces `esp32/`): `water_node.ino`, `config.h` (gitignored credentials), wiring diagram, `README.md` | 14 |
| ADS1115 I2C bring-up, per-channel PGA, calibration, validation, HTTP client with retry/buffering | 14 |
| **Delete nothing:** `esp32/README.md` is superseded — replaced only when Phase 14 rewrites that directory | 14 |

### 1.6 Documentation

| File | Change | Phase |
|---|---|---|
| `docs/api.md` | ✅ **updated in Phase 9** (proposed contract section marked NOT YET IMPLEMENTED) | — |
| `docs/PHASE_9_MIGRATION_DESIGN.md` | ✅ created in Phase 9 | — |
| `docs/PHASE_9_DASHBOARD_SPECIFICATION.md` | ✅ created in Phase 9 | — |
| `docs/PHASE_9_QUALITY_ASSESSMENT_DESIGN.md` | ✅ created in Phase 9 | — |
| `docs/PHASE_9_IMPLEMENTATION_ROADMAP.md` | ✅ this document | — |
| `docs/architecture.md`, `docs/hardware-integration.md`, `docs/machine-learning.md` | rewrite for 2-sensor/ESP8266/ADS1115 scope | 14/15 |
| `README.md`, `PROJECT_STATUS.md`, `esp32/README.md`, `ml/README.md`, `simulator/README.md`, `frontend/README.md`, `backend/README.md` | scope wording, test counts, structure | 15 |

---

## 2. Dependencies Between Future Phases

```
Phase 9 (planning) ──► approval of 5 review decisions (§5)
      │
      ▼
Phase 10 ── depends on ──► DB migration executed first (or simultaneously)
 backend/API               (nullable pH/temp + ESP8266 enum, else MySQL 1048 / 422)
      │                    └── ML skip logic depends on final ML decision (§5 D2)
      ├──► Phase 11 (ML compatibility hardening) ── uses Phase 10 schema behaviour
      ├──► Phase 12 (simulator) ── must target the Phase 10 contract
      ├──► Phase 13 (frontend) ── needs Phase 10 endpoints/fields (`score_method`,
      │        `screening_status`, `parameter_rule_check`, `ml_status`,
      │        `/api/devices`) + Phase 9 dashboard spec
      ▼
Phase 14 (ESP8266 firmware) ── needs Phase 10 contract stable + hardware bench
      ▼
Phase 15 (integration testing, docs finalisation, security hardening)
        └── depends on all of 10-14
```

**Hard ordering rules:**
1. **DB migration before ESP8266 traffic** (otherwise every hardware reading fails with a NULL-constraint error).
2. **Phase 10 contract before Phase 12 simulator and Phase 14 firmware** (one shared payload).
3. **Phase 10 endpoints before Phase 13 device-status UI** (or use the documented interim freshness fallback).
4. **Score bands/weights frozen (§5) before Phase 10**, because changing them later creates another score version.
5. Phases 11 and 12 may run in parallel with 13 once 10 is stable.

---

## 3. Recommended Implementation Sequence (Phase 10 detail)

**Phase 10 — Backend contract + assessment refactor (first implementation phase):**

1. Freeze the Phase 9 review decisions (weights, bands, `score_method` storage, ML skip policy, simulator policy).
2. Backup MySQL → apply approved migration on a restore-copy → verify → apply to real DB (per `PHASE_9_MIGRATION_DESIGN.md` §4).
3. Models: nullable `ph`/`temperature`, `DeviceSource.ESP8266`, optional `score_method`, band columns.
4. Schemas: optional `ph`/`temperature`, `source` literal + `ESP8266`, config bands, ML-status fields.
5. `quality_service`: 2-parameter score + `score_method` tag; refuse to score missing inputs.
6. `safety_service`: 2-parameter **Parameter Rule Check** (`PASS`/`WARNING`/`FAIL`, missing parameter = `UNAVAILABLE`, overall = `FAIL > WARNING > UNAVAILABLE > PASS`).
7. `reading_service`: persist NULL pH/temp; **run ML only when `ph` is present**; otherwise `prediction = NULL` + `ml_status = UNAVAILABLE` + reason; tag `score_method`.
8. `config_service`/`config.py`: retire pH/temp rules, add band validation.
9. New `routers/devices.py` (+ register); optional `routers/statistics.py`; harden `main.py` `create_all` logging.
10. Rewrite the affected test files; add the new test groups listed in §1.2.
11. Verify: full backend suite green, live `POST` with `{device_id, tds, turbidity, source: "ESP8266"}` → 201 with `prediction: null`, score present, `score_method = TWO_PARAM_SCREENING`; legacy 4-field payload still → 201 with ML verdict; regression on MySQL counts.

---

## 4. Testing Requirements

| Level | Requirements |
|---|---|
| Unit | 2-param score math & clamping, band boundaries, missing-input refusal, safety skips, config validation, ML-skip predicate, CSV null handling |
| API contract | hardware payload → 201 (pH/temp absent **and** explicit `null` both accepted); invalid → 422 matrix (missing tds, missing turbidity, negative, bool, bad source, bad device_id); legacy payload → 201 with ML; `/latest` + `/history` return `score_method` and `ml_status` |
| ML | reading without pH → `prediction IS NULL`, **never** `"NOT POTABLE"`; with pH → verdict as before; artifact unchanged (SHA-256/`feature_columns` regression) |
| DB | migration dry-run on restored copy: counts identical, pH/temp values preserved, enum widened; post-migration NULL insert works |
| Regression | entire backend suite green after rewrite; simulator suites; frontend suite after Phase 13; `npm run build` |
| Integration | end-to-end: simulated hardware payload → MySQL → API → dashboard rendering, with pH/temperature absent everywhere in the UI |
| Hardware (Phase 14/15) | bench readings, calibration checks, offline/reconnect, rejected-payload recovery, 30-day soak optional |

---

## 5. Decision Register

### Finalized (approved in the Phase 9 correction review)

| # | Decision | Final decision |
|---|---|---|
| **D1** | Score weights | ✅ **FINALIZED — TDS 0.55 (55 %) / Turbidity 0.45 (45 %)** |
| **D2** | ML policy | ✅ **FINALIZED — skip ML inference when pH is missing; return `NULL` (`ml_status: UNAVAILABLE`, reason `PH_NOT_MEASURED`); existing artifact unchanged** |
| **D3** | Score provenance | ✅ **FINALIZED — store `score_method` (`TWO_PARAM_SCREENING` vs `FOUR_PARAM_LEGACY` / `NULL` = legacy)** |
| **D4** | Screening status bands | ✅ **FINALIZED — `GOOD` ≥ 70, `MODERATE` ≥ 40 and < 70, `POOR` < 40, `UNAVAILABLE` when the score cannot be calculated** |
| **D5** | Simulator channels | ✅ **FINALIZED — two-channel (TDS + turbidity) default, optional legacy four-channel mode for regression** |
| **D6** | Device vs statistics API | ✅ **FINALIZED — device API (`GET /api/devices`, `/api/devices/{id}`) now; statistics API later (with the Analytics page)** |
| **D7** | Admin authentication | ✅ **FINALIZED — admin authentication must be addressed before deployment** (mechanism itself still pending, see below) |
| **D8** | Rule-engine terminology | ✅ **FINALIZED — display name `Parameter Rule Check` with labels `PASS` / `WARNING` / `FAIL` (missing/invalid parameter = `UNAVAILABLE`, never `PASS`); legacy `SAFE`/`UNSAFE` retained only for historical records** |

### Pending (not yet decided)

| # | Pending decision | Notes |
|---|---|---|
| **P1** | Field-level compatibility for assessments: how legacy `safety_status` (`SAFE`/`WARNING`/`UNSAFE`) is exposed alongside the new `parameter_rule_check` in `GET /api/readings/latest` and `/history`, and where per-parameter rule results are persisted (recompute at read time vs store) | To be designed in Phase 10; storage enum itself is unchanged by the migration |
| **P2** | Admin authentication mechanism for `PUT /api/config` (shared admin token vs HTTP basic auth vs middleware) | D7 requires it *before deployment*; exact mechanism TBD |
| **P3** | Simulator legacy mode flag name/UX (`--legacy-4ch` vs `--sensors`) | Policy finalized (D5), naming pending |

---

## 6. Phase 9 Compliance Confirmation

- ✅ No runtime backend code was modified.
- ✅ No runtime frontend code was modified.
- ✅ No database migration was executed.
- ✅ No historical records were changed.
- ✅ No ML model was retrained or replaced (artifact untouched).
- ✅ No packages were installed or updated.
- ✅ No files were deleted.
- ✅ No firmware was written or uploaded; no sensors were connected.

*Awaiting your review and explicit approval before starting Phase 10.*
