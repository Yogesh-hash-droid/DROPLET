# Project Audit Report — Water Potability Prediction System

> **Audit type:** Read-only. No files were modified, no packages installed, no code deleted, no model retrained.
> **Audit date:** 2026-10-30
> **Final hardware scope (authoritative):** ESP8266 NodeMCU + ADS1115 ADC + TDS sensor + Turbidity sensor.
> **Explicitly out of scope:** pH sensor, temperature sensor, ESP32-specific code.

---

## 1. Current Project Structure

```
D:\EVS\
├── .gitignore
├── README.md
├── PROJECT_STATUS.md
├── PROJECT_AUDIT_REPORT.md          ← this file (new, created by this audit)
│
├── backend/                          FastAPI application
│   ├── .env                          (gitignored, present, contains real DB password)
│   ├── .env.example
│   ├── README.md
│   ├── requirements.txt
│   ├── uvicorn_phase5.log / .err.log
│   ├── uvicorn_phase8.log / .err.log
│   ├── .pytest_cache/                (lastfailed = {} → no failures in last run)
│   ├── app/
│   │   ├── main.py                   app factory, CORS, lifespan ML warm-up, /health, /
│   │   ├── config.py                 pydantic-settings (env + defaults)
│   │   ├── database.py               SQLAlchemy engine/session, check_db_connection()
│   │   ├── models/                   device.py, water_reading.py, prediction.py, system_config.py
│   │   ├── schemas/                  device.py, water_reading.py, prediction.py, system_config.py
│   │   ├── routers/                  readings.py, config.py, predictions.py
│   │   ├── services/                 reading_service.py, safety_service.py,
│   │   │                             quality_service.py, config_service.py
│   │   └── ml/service.py             thread-safe singleton ML inference wrapper
│   └── tests/                        9 files, 119 tests
│
├── database/schema.sql               MySQL DDL (4 tables) + seed rows
│
├── docs/
│   ├── api.md                        endpoint spec (implemented + planned)
│   ├── architecture.md               system architecture
│   ├── hardware-integration.md       ESP32-centric hardware plan  ⚠ out of scope
│   └── machine-learning.md           Phase 4/5 ML report
│
├── esp32/README.md                   placeholder only  ⚠ wrong MCU for final scope
│
├── frontend/                         React 19 + Vite 8 dashboard
│   ├── src/{App.jsx,main.jsx,styles.css}
│   ├── src/pages/                    Dashboard.jsx, History.jsx, Settings.jsx (+ integration test)
│   ├── src/components/               11 components (+ 2 test files)
│   ├── src/hooks/usePolling.js       (+ test)
│   ├── src/services/api.js           axios client
│   ├── src/utils/                    constants.js, format.js, thresholds.js (+ 2 test files)
│   └── src/test/                     setup.js + 4 live-captured JSON fixtures
│
├── ml/
│   ├── pipeline.py                   dataset load/preprocess/split/CV-select/train/evaluate
│   ├── train.py                      training CLI
│   ├── evaluate.py                   independent artifact verification CLI
│   ├── predict.py                    standalone inference CLI
│   ├── README.md
│   ├── data/water_potability.csv     3 276 rows × 10 cols (Kaggle, SHA-256 verified)
│   └── models/                       water_potability_model.joblib (1.9 MB) + model_metrics.json
│
└── simulator/
    ├── sensors.py                    4-channel physical sensor model
    ├── scenarios.py                  10 scenarios
    ├── client.py                     HTTP client (POST /api/readings)
    ├── simulator.py                  CLI
    └── README.md
```

**Total:** ~75 source/config files (excluding `node_modules/`, `dist/`, caches).

---

## 2. Existing Implementation Summary

### 2.1 Backend (FastAPI + SQLAlchemy + MySQL)

| Layer | Implementation | Status |
|---|---|---|
| App | `app/main.py` — FastAPI 1.0.0, CORS locked to `localhost:5173`, ML warm-up in `lifespan`, `Base.metadata.create_all()` at import (failure silently swallowed) | Working |
| Config | `app/config.py` — pydantic-settings, `.env` override, `DATABASE_URL` override, default thresholds as settings | Working |
| DB engine | `app/database.py` — `mysql+pymysql`, pool_pre_ping, pool_recycle 3600, pool_size 10 | Working |
| Models | `Device`, `WaterReading`, `Prediction` (1:1 with reading via `reading_id` unique), `SystemConfig` (single row id=1) | Working |
| Schemas | Pydantic v2, `from_attributes`, strict bool→number rejection (`mode="before"`) on all 4 numerics | Working |
| Services | `config_service` (auto-provision defaults), `safety_service` (4-param rule engine), `quality_service` (4-param weighted score), `reading_service` (full ingestion pipeline) | Working |
| ML service | `app/ml/service.py` — lazy thread-safe singleton, artifact validated on load (`feature_columns` must equal `("ph","tds","turbidity")`, `temperature_used` must be false), graceful `None` on any failure | Working |
| Tests | 119 tests across 9 files; `.pytest_cache/v/cache/lastfailed = {}` | Passing (last recorded run) |

**API endpoints (implemented):**

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | DB connectivity probe, `healthy`/`degraded` |
| GET | `/` | Root banner |
| POST | `/api/readings` | Ingest → device upsert → safety → score → ML → persist → 201 |
| GET | `/api/readings/latest` | Latest reading + assessment |
| GET | `/api/readings/history` | `limit` (1–1000), `start_date`, `end_date` |
| GET | `/api/config` | Current thresholds |
| PUT | `/api/config` | Partial update + cross-field validation (400 on inverted ranges) |
| GET | `/api/predictions/latest` | Latest non-null ML verdict, 404 if none |

**API endpoints (documented as planned in `docs/api.md`, NOT implemented):** `GET /api/statistics`, `GET /api/devices`, `GET /api/devices/{device_id}` — all currently return 404.

### 2.2 Database (MySQL)

4 tables in `database/schema.sql`, matching the SQLAlchemy models:

- `devices` — `source ENUM('SIMULATION','ESP32')`, `status ENUM('ONLINE','OFFLINE')`, `last_seen` heartbeat.
- `water_readings` — `ph`, `tds`, `turbidity`, `temperature` all **`FLOAT NOT NULL`**, `source` enum, FK → `devices.device_id` (CASCADE).
- `predictions` — 1:1 with reading, `prediction ENUM('POTABLE','NOT POTABLE') NULL`, `confidence FLOAT NULL`, `quality_score FLOAT NOT NULL`, `safety_status ENUM('SAFE','WARNING','UNSAFE') NOT NULL`.
- `system_config` — single row, `ph_min/ph_max/tds_max/turbidity_max/temperature_min/temperature_max`, all **NOT NULL**.

Seed data: default thresholds + `SIMULATOR-001` device.

### 2.3 Machine Learning

| Item | Value |
|---|---|
| Dataset | Kaggle "Water Potability" (`adityakadiwal/water-potability`), SHA-256 verified, 3 276 raw rows × 10 cols |
| Modelled rows | 2 785 (491 rows with missing pH dropped, no fabrication) |
| **Features** | **`ph`, `tds` (dataset `Solids`), `turbidity` — exactly 3** |
| Temperature | Never used; `temperature_used: false` enforced in artifact, service, API and tests |
| Model | `RandomForestClassifier(n_estimators=200, max_depth=8, min_samples_leaf=5, seed=42)` |
| Selection | 5-fold CV ROC-AUC on train split only (4 candidates) |
| Test metrics | accuracy 0.6104 (baseline 0.6050) · ROC-AUC **0.5522** · recall(POTABLE) **0.0864** · F1(POTABLE) 0.1490 · CM TN 321 / FP 16 / FN 201 / TP 19 |
| Feature importances | ph 0.352, tds 0.345, turbidity 0.303 |
| Artifact | `ml/models/water_potability_model.joblib` (1.9 MB, present, trained 2026-10-06) |
| Verification | `ml/evaluate.py` proves 0 train/test overlap, reproducible split, exact metric match |

The model is honestly labelled **EXPERIMENTAL / ADVISORY** everywhere (API, UI, docs) and never overrides the Safety Rule Engine. This is well executed.

### 2.4 Frontend (React + Vite)

- 3 tabs (no router): **Dashboard** (sensor cards, safety panel, score gauge, ML verdict card, trend charts), **History** (time ranges, filters, table), **Settings** (threshold form, system status, latest ML verdict).
- 12 components, `usePolling` hook (with tab-focus refresh), axios service layer, Vite dev proxy `/api` + `/health` → `127.0.0.1:8000`.
- Client-side threshold-band mirror (`utils/thresholds.js`) used **only for colouring**; API `safety_status` stays authoritative.
- Safety-first UX: ML card carries EXPERIMENTAL badge + disclaimer; safety/ML disagreement highlighted.
- 28 tests (Vitest + Testing Library) using real captured API fixtures; production build succeeds.

### 2.5 Simulator

- `sensors.py`: 4 channels, baseline + gaussian noise + mean reversion + drift + events + hard per-tick delta clamp (pH ≤ 0.12, TDS ≤ 45 ppm, turb ≤ 0.7 NTU, temp ≤ 1.5 °C) + physical bounds.
- `scenarios.py`: 10 scenarios (NORMAL, PH_DRIFT_LOW, PH_DRIFT_HIGH, HIGH_TDS, HIGH_TURBIDITY, ACIDIC_WATER, ALKALINE_WATER, TEMPERATURE_SPIKE, MULTIPLE_PROBLEM, SENSOR_RECOVERY).
- Always `POST /api/readings` through the real API, `source` always `SIMULATION`, reproducible with `--seed`, errors never hidden.
- 31 tests (27 unit + 4 live auto-skip).

### 2.6 Tests and Environment

- **Backend 119 passed / Frontend 28 passed = 147 total**, 0 failures recorded.
- `backend/.env` present and correctly gitignored; `.env.example` provided; no hardcoded secrets in source.
- CORS restricted; no raw SQL string building; no stack traces leaked.
- Log files contain only INFO access logs (the 422/400 entries are deliberate negative tests).

---

## 3. Issues Found

### 3.1 CRITICAL — pH and temperature are hard-required end-to-end, but no such sensors exist

This is the single largest finding. pH and temperature are not optional anywhere in the stack:

| Location | pH / temperature requirement | Impact |
|---|---|---|
| `backend/app/schemas/water_reading.py` L8, L11 | `ph` and `temperature` are **required** fields (no default, no null) | ESP8266 payload without them → **HTTP 422**, reading rejected |
| `database/schema.sql` L25, L28 | `ph FLOAT NOT NULL`, `temperature FLOAT NOT NULL` | Cannot store a hardware reading that omits them |
| `database/schema.sql` L57–63 | `ph_min/ph_max/temperature_min/temperature_max NOT NULL` | Config table cannot exist without pH/temp thresholds |
| `backend/app/services/safety_service.py` | 4-parameter rule engine; `evaluate_safety(ph, tds, turbidity, temperature, config)` | Cannot evaluate without both values |
| `backend/app/services/quality_service.py` | **pH weight 0.35 + temperature weight 0.10 = 45% of the composite score** | Nearly half the score depends on unavailable sensors |
| `backend/app/config.py` L24–29 | 4 pH/temp default thresholds | Redundant settings |
| `simulator/sensors.py` L19 | `SENSOR_NAMES = ("ph","tds","turbidity","temperature")` | Simulator models 2 sensors that will not exist |
| `frontend/src/utils/constants.js` L1–6 | `PARAMS` = 4 entries incl. `ph`, `temperature` | Dashboard cards/charts for nonexistent sensors |
| `frontend/src/components/ThresholdSettingsForm.jsx` L4–11 | 6 form fields incl. `ph_min/ph_max/temperature_min/temperature_max` | Settings UI exposes unavailable controls |
| `frontend/src/utils/thresholds.js` | 4-key `switch`, pH ±0.5 and temperature ±5.0 °C bands | Client mirror must be reduced |
| Tests | ~117 of 119 backend tests and most frontend tests send/assert the 4-parameter contract | Near-total test refactor required |

**Consequence:** as built, the system cannot accept a single honest reading from the specified hardware.

### 3.2 CRITICAL — ML feature set is incompatible with available hardware

The model requires **`ph`, `tds`, `turbidity`**. The final hardware supplies only **`tds`, `turbidity`**.

- `app/ml/service.py` `FEATURE_COLUMNS = ("ph","tds","turbidity")` and the artifact validator **rejects** any artifact whose feature set differs — so the existing model literally cannot run without a pH value.
- The dataset has no temperature column (correctly handled), and pH is the top feature (importance 0.352) with single-feature AUC ≈ 0.517. Dropping pH removes the model's strongest (still weak) signal.
- The model is already marginal (ROC-AUC 0.5522, POTABLE recall 0.0864, barely above the 0.6047 majority baseline on accuracy). A 2-feature retrain will be weaker still.
- **There is no honest way to supply pH.** Any fabricated/defaulted pH value to keep the model alive would violate the project's own documented principle ("no fabricated values").

### 3.3 HIGH — ESP32-specific naming is embedded in the contract; no ESP8266 support exists

- `DeviceSource.ESP32 = "ESP32"` (`app/models/device.py` L11), MySQL `ENUM('SIMULATION','ESP32')` (2 tables), Pydantic `Literal["SIMULATION","ESP32"]` (`schemas/water_reading.py` L12/L55, `schemas/device.py` L10).
- Frontend: `Header.jsx` L11/L30 (mode badge + tooltip), `App.jsx` L40–42 (footer), `HistoryTable.jsx` L7 (source filter), `styles.css` L255.
- Docs: `README.md`, `docs/architecture.md`, `docs/api.md`, `docs/hardware-integration.md`, `ml/README.md`, `simulator/README.md`, `frontend/README.md`, `esp32/README.md`.
- **No ESP32 firmware code exists anywhere** — the `esp32/` folder contains only a README placeholder. So this is naming/contract debt, not a code-rewrite problem, but the `ENUM` values are baked into the database and will require a migration to change.

### 3.4 HIGH — `docs/hardware-integration.md` describes an entirely different (out-of-scope) hardware design

- Targets **ESP32** with sensors wired to the ESP32's **internal 12-bit ADC** pins (pH → GPIO 34, TDS → GPIO 35, turbidity → GPIO 32).
- Specifies an **analog pH sensor kit (SEN0161 / PH-4502C)** and a **DS18B20 OneWire temperature probe (GPIO 4, 4.7 kΩ pullup)** — both explicitly excluded from the final scope.
- **Never mentions ESP8266 or ADS1115 anywhere in the repository** (verified by search: zero hits for `ESP8266`, `ADS1115`, `NodeMCU` in all source, docs and config).
- No mention of I2C wiring, ADC addressing, PGA/gain configuration, or sensor calibration — all of which the ADS1115 + ESP8266 design requires.

### 3.5 MEDIUM — Device management and statistics endpoints are missing

- `docs/api.md` documents `GET /api/devices`, `GET /api/devices/{device_id}`, `GET /api/statistics` as planned (currently 404).
- The `Device` model with heartbeat (`last_seen`, `status`) already exists and is maintained by `reading_service`, and `schemas/device.py::DeviceResponse` is already defined — but **no device router exists**.
- There is no way to see which devices are online/offline, which matters once a real ESP8266 node is deployed. `config.DEVICE_OFFLINE_THRESHOLD_SECONDS = 30` is defined but **never used anywhere**.

### 3.6 MEDIUM — Quality score cannot be recalibrated automatically

- Weights are hard-coded in `quality_service.py` (0.35 / 0.30 / 0.25 / 0.10) and mirrored in the docstring. Removing pH (0.35) and temperature (0.10) leaves 0.55 of unnormalised weight. The weights must be explicitly renormalised (e.g. TDS 0.55 / turbidity 0.45, or 0.50/0.50) and the change documented, since historical scores would otherwise not be comparable.

### 3.7 MEDIUM — API/DB robustness and consistency gaps

1. **`violated_parameters` is not returned by `GET /api/readings/latest`** — only by the POST response. The dashboard therefore re-derives violation chips client-side from its own threshold mirror (`Dashboard.jsx` L21–26). Two sources of truth for a safety-adjacent field.
2. **`Base.metadata.create_all()` failure is silently swallowed** (`main.py` L13–17) — the API can start "healthy" against a broken/missing schema and only fail on first write.
3. **No authentication or device identity verification on `POST /api/readings`** — any client can post arbitrary data under any `device_id` (spoofing/queue-flooding risk once the device is on Wi-Fi). Acceptable for the prototype, but must be addressed before hardware deployment.
4. **MySQL charset is not pinned** — the SQLAlchemy URL has no `?charset=utf8mb4`. Captured fixtures show mojibake in `warning_message` (`"100.0 Â°C"` in `latest_unsafe_potable.json`, `history_live.json`) and in `PROJECT_STATUS.md` (`â†’`, `Â°C`), indicating an encoding problem somewhere in the write/read/console path that will surface in the UI via `SafetyPanel`.
5. **`MODEL_PATH` in `.env` is relative** (`../ml/models/...`) and depends on the process CWD being `backend/`. Launching uvicorn from any other directory silently disables ML (degrading to `prediction = NULL`).
6. **`temperature` schema bounds (−10…100 °C) are inconsistent with the score model**, which maps temperature linearly to 0 only between 0–60 °C.

### 3.8 LOW — Frontend issues

- Dead exports in `constants.js`: `SAFETY_COLORS`, `POLL_INTERVAL_MS`, `HISTORY_POLL_INTERVAL_MS` — poll intervals are instead hard-coded as literals in 4 files (`App.jsx`, `Dashboard.jsx`, `History.jsx`, `Settings.jsx`).
- `frontend/README.md` claims "17 unit tests" while `docs/architecture.md` claims "28 frontend tests" — stale counts.
- Test fixtures contain mojibake (`Â°C`) that would render verbatim in the UI.
- No `react-router`; tab state only (acceptable at this scale, noted for completeness).

### 3.9 LOW — Documentation inconsistencies

- `README.md` (root) and all architecture docs still describe **pH + TDS + Turbidity + Temperature** and **ESP32** as the target system.
- `ml/README.md` test arithmetic ("57 + 14 + 14 + 31 + 3") is stale relative to the current 119-test suite.
- `docs/architecture.md` L66 contains mojibake (`â‰ˆ`).
- `esp32/README.md` shows a payload containing `ph` and `temperature` and `source: "ESP32"` — every field of which is wrong for the final scope.

### 3.10 LOW — Minor code observations

- `app/models/water_reading.py` imports `Integer` (used) but `prediction.py`/`device.py` are clean; no functional defects found in the service layer.
- `Predictions` router orders by `timestamp` then `id` — correct.
- `Prediction.prediction` correctly persists enum **values** (`NOT POTABLE`) via `values_callable` — this was a previously fixed bug and is verified.
- Simulator `client.py` `source` constant is `SIMULATION` and cannot be overridden — correct by design, but means the simulator can never impersonate hardware (good).

---

## 4. Required Corrections

> These are requirements derived from the final hardware scope. Nothing here has been applied yet.

### R1 — Remove pH and temperature from the ingestion contract (blocking)

- `WaterReadingBase`: drop `ph` and `temperature` (or make them optional/nullable with `None` default, see R2 for the data-migration choice).
- `WaterReadingResponse`, `ReadingIngestionResponse`: drop the same fields.
- `database/schema.sql`: `ph` and `temperature` become `FLOAT NULL` (or columns are removed); `system_config` loses `ph_min`, `ph_max`, `temperature_min`, `temperature_max`.
- Write an explicit migration script for existing MySQL data (`ALTER TABLE … MODIFY … NULL`, plus a decision on how historical rows are treated).
- **Choose one migration strategy up front:**
  - **(a) Drop the columns** — cleanest, but loses historical pH/temperature data and breaks score comparability.
  - **(b) Make columns nullable and keep them** — preserves history, allows simulator to optionally still exercise the 4-param path, and makes the API tolerant. **Recommended**, since it is the least destructive and matches the "do not delete unnecessarily" constraint.

### R2 — Decide the ML strategy (blocking, requires an explicit product decision)

Because the model needs pH and the hardware cannot provide it, exactly one of the following must be chosen:

| Option | Description | Consequence |
|---|---|---|
| **A. Disable ML for hardware readings** (recommended short-term) | Keep the artifact and service untouched. When `ph` is absent, `ml_service.predict_reading()` returns `None` → `prediction = NULL`, `confidence = NULL`. This path **already exists and is tested** (`test_ml_failure_keeps_safety_working`). | ML panel honestly shows "no verdict". Safety engine unaffected. Zero model risk. |
| **B. Retrain on `tds` + `turbidity` only** (medium-term) | Change `FEATURE_COLUMNS` to 2 features, retrain, re-validate. Requires relaxing the artifact feature-set check in `app/ml/service.py`. | Expect metrics to fall below the current weak 0.5522 ROC-AUC; must be reported honestly, or the ML feature may be better removed entirely. |
| **C. Add a pH sensor** | Excluded by the final scope. | Not available. |

**Recommendation:** implement **A** now (schema/service tolerance for missing `ph`), evaluate **B** later as an explicitly labelled experiment with its own honest metrics. Do not fabricate pH values under any circumstance.

### R3 — Renormalise the Water Quality Score

With only TDS and turbidity sensed, the score must be recomputed from the remaining parameters, e.g. `TDS 0.55 / Turbidity 0.45` (or 0.50/0.50), with the docstring, `docs/` and the frontend `scoreBand` expectations updated. Document that scores before and after the change are not directly comparable.

### R4 — Replace ESP32 naming with a hardware-neutral or ESP8266 value

- `DeviceSource`: add `ESP8266` (or generalise to `HARDWARE`); MySQL `ENUM` values must be migrated in `devices.source` and `water_readings.source`.
- Pydantic `Literal` types, frontend `Header.jsx` / `App.jsx` / `HistoryTable.jsx` / `styles.css`, and all docs updated consistently.
- Rename the `esp32/` directory to `esp8266/` (or `hardware/`) and rewrite its README for the actual payload (2 sensor fields).

### R5 — Rewrite hardware documentation for ESP8266 + ADS1115

`docs/hardware-integration.md` must be replaced with a design covering:
- ESP8266 NodeMCU (single 10-bit ADC on `A0`, onboard divider ~3.2 V max) — insufficient for two analog sensors and out of range for a 0–4.5 V turbidity probe.
- **ADS1115** I2C 16-bit ADC (address `0x48`, SDA → `D2`/GPIO4, SCL → `D1`/GPIO5, VDD 3.3 V, GND): TDS → `A0`, Turbidity → `A1`, with PGA/gain set per sensor range and appropriate attenuation for the 4.5 V turbidity output.
- Calibration procedure for each sensor (TDS cell constant / temperature compensation is out of scope; turbidity points using formazin/Nephelometric standards or a practical proxy).
- Wi-Fi provisioning, HTTP POST cadence, retry/backoff, offline buffering.
- No pH circuitry, no DS18B20, no ESP32 pin mappings.

### R6 — Add the missing device-management surface

- Implement `GET /api/devices` and `GET /api/devices/{device_id}` (the `Device` model, heartbeat and `DeviceResponse` schema already exist).
- Apply `DEVICE_OFFLINE_THRESHOLD_SECONDS` to compute `ONLINE`/`OFFLINE` at read time.
- Optional: `GET /api/statistics` (counts, potability ratio, averages, mean score) as already reserved in `docs/api.md`.

### R7 — API/DB hardening

- Return `violated_parameters` from `GET /api/readings/latest` (and `/history`) so the frontend stops re-deriving safety data client-side.
- Pin MySQL charset (`?charset=utf8mb4`) and fix the `Â°C` mojibake end-to-end.
- Log (at least warn) on `create_all()` failure instead of bare `pass`.
- Resolve `MODEL_PATH` relative to the config file, not the CWD.
- Before hardware deployment: add a per-device API key or token on `POST /api/readings`.

### R8 — Update the simulator to the 2-sensor scope

`sensors.py` / `scenarios.py` / `client.py` must emit the reduced payload (drop the pH and temperature channels and the `PH_DRIFT_*`, `ACIDIC`, `ALKALINE`, `TEMPERATURE_SPIKE` scenarios, or repurpose them), so that simulated telemetry and real telemetry share one identical contract.

### R9 — Update the frontend

- `constants.js` `PARAMS` → 2 entries (`tds`, `turbidity`) with correct units/colours.
- `ThresholdSettingsForm` → `tds_max`, `turbidity_max` only; remove pH/temperature validation rules.
- `thresholds.js` → 2-key `switch`; remove ±0.5 pH and ±5.0 °C bands.
- `Dashboard.jsx` / `History.jsx` default chart selections → 2 keys.
- Header/footer/HistoryTable source labels → ESP8266/hardware-neutral.
- Regenerate the 4 JSON fixtures (they currently contain pH, temperature and mojibake).
- Update or remove tests asserting pH/temperature behaviour.

### R10 — Refactor the test suite

- `test_phase3_services.py` (**all 31 tests** call `evaluate_safety`/`calculate_water_quality_score` positionally with 4 values) must be rewritten for the 2-parameter signatures.
- `test_simulator.py` payload-contract test asserts the exact 6-key set — must become 4 keys (`device_id`, `tds`, `turbidity`, `source`).
- `test_phase5_ml_api.py`, `test_readings_unit.py`, `test_readings_integration.py`, `test_phase3_api.py`, `test_simulator_integration.py` all embed pH/temperature payloads or assertions.
- Only `test_health.py` (2 tests) survives unchanged. **Budget for ~110+ test modifications.**
- Add new tests: missing-`ph` ML degradation (already exists, keep), 2-param safety bands, score renormalisation, device endpoints, ESP8266 source enum.

---

## 5. Recommended Phase-by-Phase Implementation Plan

> Phase numbering continues from the existing project's Phase 8 (completed).

### Phase 9 — Scope reconciliation & contract redesign *(no behaviour change yet)*
- Agree the R1(b) nullable-column strategy and the R2(A) ML policy.
- Produce a migration script (`database/migrations/`) for nullable `ph`/`temperature` and the new `source` enum value.
- Update `docs/api.md` contract to the 2-sensor payload; mark pH/temperature as legacy/optional.
- **Exit criteria:** migration reviewed; contract signed off; no runtime change.

### Phase 10 — Backend 2-sensor refactor
- Schemas → optional `ph`/`temperature`; safety engine and quality service gain 2-parameter evaluation with renormalised weights (R3); config endpoints reduce to `tds_max`/`turbidity_max` (legacy keys tolerated).
- Implement `GET /api/devices`, `GET /api/devices/{id}`, apply `DEVICE_OFFLINE_THRESHOLD_SECONDS` (R6).
- Return `violated_parameters` from `/readings/latest`; pin charset; log `create_all` failures; fix `MODEL_PATH` resolution (R7).
- **Exit criteria:** `POST /api/readings` with `{device_id, tds, turbidity, source}` returns 201, safety + score computed, `prediction = null`; device endpoints live.

### Phase 11 — ML compatibility layer
- Make `FEATURE_COLUMNS` handling tolerant of a pH-less pipeline (R2A): skip inference and store `NULL` when `ph` is absent; keep the artifact validator strict for the 3-feature model.
- Document in `docs/machine-learning.md` that ML is inactive in hardware mode.
- (Optional, separate experiment) Prototype the 2-feature retrain offline and report its honest metrics before any decision.
- **Exit criteria:** hardware-shaped readings never crash ML; NULL verdict surfaced honestly by API and UI.

### Phase 12 — Simulator realignment
- Reduce channels/scenarios to TDS + turbidity; keep `source: "SIMULATION"`; keep reproducibility and error transparency.
- **Exit criteria:** simulator payload is byte-identical in shape to the future ESP8266 payload (minus `source`).

### Phase 13 — Frontend realignment
- Apply R9; regenerate fixtures; update tests; verify dashboard/history/settings against the 2-sensor API.
- **Exit criteria:** `npm test` and `npm run build` pass; no pH/temperature controls remain.

### Phase 14 — ESP8266 + ADS1115 firmware
- Create `esp8266/` (replacing `esp32/`): firmware `.ino`/`.cpp`, wiring diagram, pin table, calibration notes, `README.md`.
- ADS1115 I2C bring-up, per-channel PGA configuration, TDS/turbidity calibration, JSON POST with `source: "ESP8266"`, Wi-Fi reconnect/backoff, optional local buffering.
- **Exit criteria:** a bench node posts valid readings that appear on the dashboard.

### Phase 15 — Integration testing & hardening
- Hardware-in-the-loop test matrix: normal / high TDS / high turbidity / offline node / DB down / ML unavailable.
- Update every document (root `README.md`, `PROJECT_STATUS.md`, `docs/*`, sub-READMEs) to the final scope; fix stale test counts and mojibake.
- Security pass: per-device credentials, rate limiting, CORS review for the deployed origin.
- **Exit criteria:** full 4-component system (ESP8266 → FastAPI → MySQL → React) verified end-to-end; docs match reality.

---

## 6. Summary of Current Status

| Aspect | Status |
|---|---|
| Backend application, ML compatibility, simulator, frontend, tests | **Existing implementation substantially covers the Phase 10/11 application work; production acceptance remains gated** |
| pH + temperature handling | **Optional in the application contract; missing values remain NULL, but production schema migration is not approved** |
| ML vs. hardware compatibility | **Resolved in application behavior: pH-less hardware readings skip ML and surface an explicit unavailable result** |
| ESP8266 / ADS1115 support | **Application contract recognizes ESP8266; physical firmware/hardware integration remains future work** |
| Device management & statistics endpoints | **Missing (documented as planned)** |
| Score recalibration, charset/mojibake, auth | **Outstanding or separately gated as documented** |

**Bottom line:** the software system is well built, well tested and honestly documented — but it was built for a **different hardware scope**. The transition to the final ESP8266 + ADS1115 + TDS + Turbidity scope is a substantial, cross-cutting refactor (contract, database, rule engine, scoring, ML policy, simulator, UI, tests and documentation), not an incremental addition. The recommended path is Phases 9–15 above, starting with an explicit decision on the ML strategy (R2).

*Audit complete. Awaiting further instructions.*

## 7. Phase 10 / Phase 11 Documentation Reconciliation (2026-10-31)

The application tree now contains the documented Phase 11 ML compatibility
behavior, while formal phase acceptance remains gated:

- The final hardware mode measures **TDS and turbidity** only. pH and
  temperature are not measured.
- Missing pH is preserved as `NULL`. No synthetic pH, default, or imputation
  is permitted.
- ML inference is skipped when pH is unavailable and returns/stores:
  `prediction = NULL`, `confidence = NULL`,
  `ml_status = UNAVAILABLE`, and
  `ml_status_reason = PH_NOT_MEASURED`.
- Safety-rule evaluation and the two-parameter quality score continue normally.
- Readings containing pH retain the existing three-feature ML inference path.
- The existing three-feature ML artifact is unchanged. Required Phase 11 does
  not include two-feature retraining.

### Acceptance and authorization status

| Area | Current status |
|---|---|
| Phase 10 application implementation / Workstream A | **Substantially implemented** |
| Test/staging migration rehearsal | **Passed in isolated rehearsal environments** |
| Test database migration | Separate from production; not evidence of production authorization |
| Production database migration / Gate 3 | **NOT APPROVED — BLOCKED** |
| Production deployment | **NOT AUTHORIZED** |
| Gate 4 full regression and MySQL integration | **Pending / blocked until Gate 3 is approved and completed** |
| Gate 5 Phase 11 formal acceptance | **Pending / blocked until Gate 4 review and explicit approval** |

The test database and any staging or rollback rehearsal database are separate
from the production database `water_quality_db`. Passing tests or migration
rehearsals must not be interpreted as production migration approval or formal
Phase 10 acceptance. No production migration or production deployment is
claimed here.
