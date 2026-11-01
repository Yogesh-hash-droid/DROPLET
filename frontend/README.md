# Frontend Dashboard - Smart Water Quality Monitoring

Real-time telemetry dashboard built with **React 19**, **Vite**, **Recharts**, **Axios** and **Lucide icons**.

> **Status: implemented (Phase 7).** The dashboard consumes the live FastAPI
> backend through the Vite dev proxy (`/api` + `/health` → `http://127.0.0.1:8000`).
> ML potability values (`prediction`, `confidence`) are displayed as an
> **EXPERIMENTAL / ADVISORY** indicator only — the Safety Rule Engine verdict is
> always presented as authoritative, and a `POTABLE` prediction never means the
> water is certified safe.

## Features
- **Dashboard**: latest-reading sensor cards (pH, TDS, Turbidity, Temperature) colour-coded with the same threshold bands as the rule engine; Safety Rule verdict panel (status, explanation, violated parameters); Water Quality Score gauge (0-100); dual-verdict ML card with confidence bar, automatic **safety/ML disagreement** highlight and disclaimer; Recharts telemetry trends with per-parameter toggles.
- **Prominent operation mode indicator**: `SIMULATION` vs `REAL HARDWARE` badge driven by `source` (SIMULATION = software-generated data from `simulator/`, **not** real ESP32 hardware) plus a live API health dot and last-reading age.
- **History & logs**: 1h / 6h / 24h / 7d ranges, auto-refreshing charts, filterable table (safety status, source, device id, "only safety/ML disagreements").
- **Settings**: threshold configuration editor (`GET`/`PUT /api/config`, client- and API-validated), system status panel (health, database, version) and latest stored ML verdict with model inputs and disclaimer.
- Polling every 5 s (dashboard) / 10 s (history), paused-fetch resume on tab focus, and API errors surfaced in an inline banner — never hidden.

## Running Locally
```bash
npm install
npm run dev
```
Runs at `http://localhost:5173`. The backend must be running on port 8000:

```bash
cd ../backend
uvicorn app.main:app --reload --port 8000
```

To point the proxy at another backend: `VITE_API_TARGET=http://host:port npm run dev`.

Other scripts:

```bash
npm test        # vitest unit tests (no backend required)
npm run build   # production build → dist/
npm run preview # serve the production build
```

## Structure
```
src/
├── App.jsx                 # shell, nav, top-level polling (health, latest, config)
├── pages/                  # Dashboard, History, Settings
├── components/             # Header, SensorCard, SafetyPanel, ScoreGauge,
│                           # MLVerdictCard, TrendChart, HistoryTable,
│                           # ThresholdSettingsForm, SafetyBadge, StatusBanner
├── hooks/usePolling.js     # interval polling with error surfacing
├── services/api.js         # Axios client for /api/* + /health
├── utils/                  # constants, format helpers, threshold band mirror
└── styles.css              # dark theme, responsive layout
```

`utils/thresholds.js` mirrors the backend Safety Rule Engine bands purely to
colour individual cards; the authoritative verdict is always the API's
`safety_status`.

## Tests
17 unit tests (Vitest + Testing Library, no server needed): threshold-band
mirror for all four parameters, formatting/score-band helpers, sensor card
status rendering, and ML card behaviour (disclaimer, disagreement, missing
verdict).
