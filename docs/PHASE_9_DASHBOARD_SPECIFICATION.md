# Phase 9 — Final Dashboard Feature Specification

> **Status:** SPECIFICATION ONLY — **the React frontend was not modified in Phase 9.**
> **Target:** React + Vite + JavaScript (existing stack; no new packages assumed).
> **Display rule:** the new dashboard shows **TDS and turbidity only** — no pH cards, no temperature cards, no pH/temperature charts, no pH/temperature threshold controls.
> **Related:** `docs/PHASE_9_QUALITY_ASSESSMENT_DESIGN.md` · `docs/api.md` · `docs/PHASE_9_IMPLEMENTATION_ROADMAP.md`

---

## 1. Design Principles

- Professional IoT monitoring interface: clean, modern, consistent spacing/typography/color.
- Responsive: desktop (≥1024 px), tablet (≥768 px), mobile (single-column, ≥360 px).
- Safety-first honesty: every assessment surface is labelled *preliminary screening*; the ML model is never used to generate the score; missing data is always shown as missing.
- **Drinking-water safety disclaimer stays visible at all times** (footer on every page): educational prototype — not a substitute for certified laboratory water testing.
- **A `PASS` Parameter Rule Check or `GOOD` score must never be rendered or worded as confirmation that the water is potable.**
- Four universal states everywhere: **loading**, **ready**, **empty**, **error/disconnected**.
- No unnecessary sensor cards — exactly two measurement cards (TDS, turbidity).

---

## 2. Navigation (5 pages)

Recommended: keep the current lightweight tab-state navigation (no router dependency) — pages below map to tabs. A router can be introduced later without changing this spec.

| Page | Route/tab key | Purpose |
|---|---|---|
| **Dashboard** | `dashboard` | Live values, score, status, device/sensor status, last updated, short trend |
| **History** | `history` | Tabular historical readings with filters |
| **Analytics** | `analytics` | Longer-range trend charts and aggregates |
| **Reports** | `reports` | Export/download of historical readings |
| **Settings** | `settings` | Thresholds, system health, device list, ML availability note |

Persistent chrome: app header (title, connection indicator, last-updated badge), footer disclaimer (educational prototype / laboratory testing required).

---

## 3. Feature Specification

### F1 — Live Sensor Values
- Two cards: **TDS** (`ppm`) and **Turbidity** (`NTU`).
- Each card: value with unit, measurement label, per-sensor status chip, threshold hint (configured `tds_max` / `turbidity_max`), timestamp of the reading shown.
- States:
  - **Loading** — skeleton placeholder, no fabricated zeros.
  - **Unavailable** — value `null` → em dash `—` + "not measured" chip (never `0`).
  - **Sensor error** — reading present but API reports an assessment problem, or device offline → error chip with reason.
  - **API error** — inline banner with the API message; last known values retained but visibly aged.
- Data: `GET /api/readings/latest`.

### F2 — Water Quality Score (0–100)
- Gauge or radial bar (reuse the existing `ScoreGauge` idea) showing the **two-parameter screening score**.
- Label: **"Preliminary Screening Score (TDS + Turbidity)"**.
- Must display `score_method`; if the underlying row is a legacy 4-parameter score, show a **"Legacy score (4-parameter)"** tag instead of silently presenting it as the new score.
- Score `null` → "Score unavailable" state with reason (missing/invalid reading).
- **The 3-feature ML model must not be used to compute or adjust this score.**

### F3 — Preliminary Screening Status
- Chip/badge: **`GOOD`** / **`MODERATE`** / **`POOR`** / **`UNAVAILABLE`** (bands per quality-assessment design: `GOOD` ≥ 70, `MODERATE` 40–69.9, `POOR` < 40, `UNAVAILABLE` when the score cannot be calculated).
- One-line explanation under the badge (config-driven text, e.g. "Preliminary screening score for TDS and turbidity is within the configured acceptable range.").
- Colour: green/amber/red/grey, always accompanied by text (never colour alone — accessibility).
- Must carry the qualifier **"preliminary screening status"** and must never read "certified safe", "verified" or "drinkable".
- `UNAVAILABLE` must never be rendered as one of the three scored bands, and a missing score must never be shown as `0`.

### F3B — Parameter Rule Check
- A separate panel (distinct from the score): display name **"Parameter Rule Check"**.
- Overall badge: **`PASS`** / **`WARNING`** / **`FAIL`** (plus `UNAVAILABLE` when no parameter could be evaluated).
- Per-parameter rows: **TDS** and **Turbidity** — measured value + unit + `PASS`/`WARNING`/`FAIL`/`UNAVAILABLE` chip + the detail line from the API (e.g. "TDS (650.0 ppm) is above the configured threshold (500.0 ppm)").
- A missing/invalid value renders as **Unavailable** — never as `PASS`, never as a blank treated as passing.
- Persistent qualifier: **"Two-parameter check only — a `PASS` result does not mean the water is potable, certified or safe to drink."**
- The labels `SAFE` / `UNSAFE` are not used for this panel (`WARNING` keeps its wording). For legacy rows the historical `safety_status` may be shown in a clearly tagged **"legacy assessment (4-parameter)"** line instead.
- The Parameter Rule Check and the screening score are always shown as **two independent outputs** (they may differ).
- Data: `parameter_rule_check` from `GET /api/readings/latest` / `/history` (proposed contract, `docs/api.md`).

### F4 — ESP8266 Connection Status
- Header indicator + a device panel: **Connected / Disconnected / Unknown**.
- Connectivity determination (design):
  - **Primary (after Phase 10 device endpoints):** `GET /api/devices` computes status from `last_seen` against `DEVICE_OFFLINE_THRESHOLD_SECONDS` (existing setting, 30 s) → `ONLINE` / `OFFLINE`.
  - **Interim fallback:** freshness of `GET /api/readings/latest` where `source = "ESP8266"`: age ≤ threshold → Connected; older → Disconnected (with "stale" wording); never seen → "No hardware device registered".
  - Show the age of the last packet ("last seen 12 s ago"); if age > threshold, the dashboard enters the **stale-data** state (muted values + banner), regardless of page.
- Never show "Connected" on the basis of API health alone — API health and device health are separate indicators.

### F5 — Sensor Status
- Per-sensor status list: **TDS sensor**, **Turbidity sensor**.
- States per sensor: **Working** (recent value, within physical validation range), **Unavailable** (value `null` / never reported), **Error** (device offline or repeated invalid/rejected readings reported by the API).
- Determined from: the presence of a value in the latest reading + device connectivity + API `detail` messages from rejected payloads.

### F6 — Last Updated Timestamp
- Uses the **reading's own `timestamp`** (not the fetch time).
- Display: absolute date-time + relative age ("2026-10-30 14:02:11 · 8 s ago").
- Staleness rules: `≤ threshold` normal; `> threshold` → amber "stale data" badge; `> 5× threshold` → red "no recent data" + banner. Relative age refreshes at least every second via the existing polling/interval pattern.

### F7 — Historical Readings
- Table columns: timestamp, TDS (ppm), turbidity (NTU), screening score, status, `score_method`, device, source.
- **No pH or temperature column.** (Legacy values still exist in the DB but are out of the new display scope.)
- Filters: time range (1 h / 6 h / 24 h / 7 d / custom), device, source, status band, "score method" (legacy vs new), search by device id.
- Paging/virtualisation for large sets; empty state ("No readings in this range"); loading skeleton; API error banner.
- Data: `GET /api/readings/history` (+ later `GET /api/devices` for the device filter list).

### F8 — Trend Charts
- Two separate charts (or two toggleable series): **TDS trend (ppm)** and **Turbidity trend (NTU)**.
- Time ranges: 1 h, 6 h, 24 h, 7 d (reuse existing `TIME_RANGES`).
- **No pH or temperature series.**
- Gaps rendered as gaps — a `null` value must not be interpolated into a fake line segment or drawn as zero.
- Readable axes/units, tooltips with timestamp + value, empty/loading/error states, responsive to container width.

### F9 — Download Report
- On the **Reports** page (and an "Export CSV" action on History):
  - Columns: `timestamp`, `device_id`, `source`, `tds_ppm`, `turbidity_ntu`, `screening_score`, `score_method`, `screening_status`, `parameter_rule_check_status` (and, for legacy rows, `legacy_safety_status`).
  - Filename pattern: `water_readings_YYYYMMDD_HHMM.csv`.
  - Missing values exported as **empty cells** (never `0`, never a default).
  - Client-side generation from already-fetched history data (Blob + `URL.createObjectURL`) — **no new package required**; a `GET /api/readings/export` endpoint is an optional later enhancement.
  - Include a header comment row with the export time and the disclaimer line.

### F10 — Configurable Thresholds (Settings)
- Fields: `tds_max`, `turbidity_max`, `status_good_min`, `status_poor_max`.
- Client validation mirrors server rules (numeric, `≥ 0`, `0–100` for bands, `poor_max < good_min`), with inline errors; server `400/422` messages surfaced verbatim.
- Explanation text: **changes affect future assessments only** — stored scores and history are not recalculated.
- Access control: documented as "administrator" configuration. Phase 9 records the requirement for an authorisation mechanism (e.g. shared admin token / basic auth on `PUT /api/config`) as an open security decision for Phase 10/15 — today `PUT /api/config` is unauthenticated.
- Legacy pH/temperature threshold fields are **not shown** in the new UI.

### Additional (Settings page)
- System health panel (`GET /health`): API status, DB connectivity, environment, version.
- Device list (`GET /api/devices`, planned): id, name, source, status, last seen.
- ML availability note: explain that ML predictions require pH and are therefore `null`/unavailable for ESP8266 hardware readings; show legacy ML verdicts only if `GET /api/predictions/latest` returns one, clearly tagged "legacy reading".

---

## 4. Proposed Component Structure

```
frontend/src/
├── App.jsx                      # tab state: dashboard | history | analytics | reports | settings
├── components/
│   ├── Header.jsx               # brand, nav tabs, API health dot, device-status dot, last-updated badge
│   ├── StatusBanner.jsx         # ErrorBanner / LoadingNote (existing)
│   ├── StaleDataBanner.jsx      # NEW - stale/disconnected warnings
│   ├── EmptyState.jsx           # NEW - reusable empty/no-data placeholder
│   ├── SensorCard.jsx           # REUSE - parameter-driven; receives only tds & turbidity definitions
│   ├── SensorStatusList.jsx     # NEW - per-sensor Working / Unavailable / Error
│   ├── DeviceStatusCard.jsx     # NEW - ESP8266 connection + last-seen age
│   ├── ScoreGauge.jsx           # REUSE - relabel "Preliminary screening score"
│   ├── ScreeningStatusBadge.jsx # NEW - GOOD / MODERATE / POOR / UNAVAILABLE + explanation
│   ├── ParameterRuleCheckPanel.jsx # NEW - Parameter Rule Check: PASS / WARNING / FAIL + per-parameter rows
│   ├── MLVerdictCard.jsx        # ADAPT - show "ML unavailable (pH not measured)" for new readings
│   ├── TrendChart.jsx           # REUSE - series limited to tds & turbidity
│   ├── HistoryTable.jsx         # REUSE - new columns/filters, drop pH/temp, add score_method
│   ├── ThresholdSettingsForm.jsx# ADAPT - 2 threshold fields + 2 band fields, no pH/temp
│   ├── DeviceListPanel.jsx      # NEW - planned GET /api/devices
│   └── ExportControls.jsx       # NEW - date range + Download CSV
├── pages/
│   ├── Dashboard.jsx            # ADAPT - 2 sensor cards, score, status, device/sensor status, short trend
│   ├── History.jsx              # ADAPT - table + filters + export shortcut
│   ├── Analytics.jsx            # NEW - multi-range trends + aggregates
│   ├── Reports.jsx              # NEW - export configuration + download
│   └── Settings.jsx             # ADAPT - thresholds, health, devices, ML note
├── hooks/
│   ├── usePolling.js            # REUSE unchanged
│   └── useStaleness.js          # NEW - timestamp → fresh | stale | offline
├── services/api.js              # ADAPT - add fetchDevices (planned), export helper
├── utils/
│   ├── constants.js             # ADAPT - PARAMS = [tds, turbidity]; status bands; disclaimer
│   ├── thresholds.js            # ADAPT - 2-parameter evaluation only
│   ├── screeningScore.js        # NEW - client-side mirror of the 2-param score (display only)
│   ├── format.js                # REUSE - add formatAge/formatCsv helpers
│   └── exportCsv.js             # NEW - CSV generation
└── test/fixtures/               # REGENERATE - 2-sensor payloads, no pH/temp, no mojibake
```

---

## 5. Data Requirements per Page

| Page | Endpoints | Key fields |
|---|---|---|
| Dashboard | `GET /api/readings/latest`, `GET /api/readings/history?limit=…`, `GET /api/config`, `GET /health`, (`GET /api/devices` planned) | `tds`, `turbidity`, `timestamp`, `quality_score`, `score_method`, `screening_status`, `parameter_rule_check`, `prediction`, `source`, `device_id` |
| History | `GET /api/readings/history` (limit/start/end), `GET /api/config` | as above per row |
| Analytics | `GET /api/readings/history` (large ranges), `GET /api/statistics` (planned) | aggregates, series |
| Reports | `GET /api/readings/history` (selected range) | export columns (F9) |
| Settings | `GET/PUT /api/config`, `GET /health`, `GET /api/predictions/latest`, (`GET /api/devices` planned) | thresholds, health, ML availability |

**Not required anywhere:** `ph`, `temperature`, `temperature_used`, pH/temperature threshold fields (except that `GET /api/config` will still return legacy keys until the API is relaxed — the UI simply ignores them).

---

## 6. Cross-Cutting States

| State | Trigger | UI response |
|---|---|---|
| Loading | first fetch, no data yet | skeletons, no zeroed values |
| Empty | history range has no rows | empty-state illustration + guidance |
| Stale | last reading older than offline threshold | aged badge, muted cards, banner |
| Disconnected | device offline (or never seen) | red indicator + "ESP8266 not connected" |
| API error | request failed / 4xx-5xx | inline error banner with API `detail`, data retained |
| Unavailable value | `null` sensor value or `null` score | `—` + "not measured"/"unavailable" chip |
| Legacy data | `score_method` legacy or pH-bearing row | explicit "legacy" tags; pH/temperature **not** rendered |

---

## 7. Explicit Non-Goals for the New Dashboard

- No pH card, pH chart, pH filter, pH threshold field.
- No temperature card, chart, filter or threshold field.
- No rendering of legacy pH/temperature history (values remain in the database, out of display scope).
- No ML-generated score; no presentation of ML as a safety certification.
- No fabricated/defaulted sensor values anywhere.

---

## 8. Testing Requirements (for later phases)

- Unit: screening-score mirror, status bands, Parameter Rule Check bands/overall ordering, staleness hook, CSV generation (incl. `null` → empty cell).
- Component: SensorCard states (ready/unavailable/error), ScreeningStatusBadge, ParameterRuleCheckPanel (PASS/WARNING/FAIL + unavailable parameter is never PASS), DeviceStatusCard, MLVerdictCard "unavailable vs NOT POTABLE" distinction.
- Page integration with regenerated fixtures (2-sensor payloads).
- Regression: assert **absence** of pH/temperature UI elements (query by test id and expect none).
- Responsive checks at 360 / 768 / 1280 px; build + full suite must pass.

---

*Phase 9 documentation only — no React code was created or modified.*
