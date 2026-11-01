# System Architecture

## Overview
The Smart Water Quality Monitoring and Potability Prediction System is architected around the **Pluggable Data Source Pattern**. Data ingress can originate from the software simulator (`simulator/`, Phase 6) or a physical IoT device (ESP32) over Wi-Fi without impacting core processing logic.

```
+-------------------------------------------------------------+
|                     Data Sources                            |
|                                                             |
|   +-----------------------+     +-----------------------+   |
|   | Simulator (Phase 6)   |     |   Physical ESP32      |   |
|   | source: "SIMULATION"  |     |   (source: "ESP32")   |   |
|   | software-generated    |     |   not yet implemented |   |
|   +-----------+-----------+     +-----------+-----------+   |
+---------------|-----------------------------|---------------+
                |                             |
                +--------------+--------------+
                               |
                               | HTTP POST /api/readings
                               v
+-------------------------------------------------------------+
|                      FastAPI Backend                        |
|                                                             |
|  +--------------------+     +----------------------------+  |
|  | Schema Validation  | --> | MySQL Database Persistence |  |
|  +---------+----------+     +----------------------------+  |
|            |                                                |
|            +-----------------------+                        |
|            |                       |                        |
|            v                       v                        |
|  +-------------------+   +--------------------+             |
|  | Safety Rule       |   | ML Potability      |             |
|  | Engine            |   | Engine (Scikit)    |             |
|  | (Deterministic)   |   | (Probabilistic)    |             |
|  +---------+---------+   +---------+----------+             |
|            |                       |                        |
|            +-----------+-----------+                        |
|                        |                                    |
|                        v                                    |
|              +-------------------+                          |
|              | Water Quality     |                          |
|              | Score (0-100)     |                          |
|              +---------+---------+                          |
|                        |                                    |
|                        v                                    |
|              +-------------------+                          |
|              | Prediction Record |                          |
|              | Stored to MySQL   |                          |
|              +-------------------+                          |
+-------------------------------------------------------------+
                               |
                               | REST API (Polling)
                               v
+-------------------------------------------------------------+
|                  React + Vite Dashboard                     |
|                                                             |
|  - Real-time Sensor Telemetry (pH, TDS, Turbidity, Temp)   |
|  - Prominent Operation Mode Badge (SIMULATION vs HARDWARE)  |
|  - Independent Dual Verdicts (Rule Engine + ML Potability)  |
|  - Water Quality Score (0-100)                             |
|  - Historical Charts (Recharts)                             |
|  - Device Heartbeat & Settings Management                   |
+-------------------------------------------------------------+
```

> **Implementation status (end of Phase 8):** Schema validation, MySQL persistence, Safety Rule Engine, Water Quality Score (0-100), the ML training pipeline, the ML inference API (`prediction`, `confidence`, `GET /api/predictions/latest`), the multi-scenario simulator (`simulator/`) and the React + Vite dashboard (`frontend/`) are implemented and verified. Phase 8 hardened and re-verified the full stack (119 backend tests + 28 frontend tests, end-to-end pipeline, API edge cases, ML-failure resilience, DB failure/recovery, CORS, security scan). The ML verdict is **EXPERIMENTAL / ADVISORY** (weak model, ROC-AUC â‰ˆ 0.552) and never overrides the rule engine. ESP32 firmware is **not yet implemented**.

## Simulator (Phase 6)

`simulator/` generates the telemetry that would otherwise come from hardware:

- **`SIMULATION` = software-generated sensor data**, never real ESP32 readings. The field is always `"source": "SIMULATION"`; real firmware will send `"source": "ESP32"` with the identical JSON contract.
- Realistic sensor model: baseline + gaussian noise + mean reversion + gradual drift + occasional self-recovering events, with a hard per-tick delta limit (no unrealistic jumps).
- Ten selectable scenarios (`NORMAL`, `PH_DRIFT_LOW`, `PH_DRIFT_HIGH`, `HIGH_TDS`, `HIGH_TURBIDITY`, `ACIDIC_WATER`, `ALKALINE_WATER`, `TEMPERATURE_SPIKE`, `MULTIPLE_PROBLEM`, `SENSOR_RECOVERY`), documented in `simulator/README.md`.
- Sends only through `POST /api/readings`, so safety rules, the Water Quality Score and ML inference all run in the real backend.
- CLI: `python simulator/simulator.py --scenario normal --interval 3 --count 20 [--seed N] [--dry-run]`.

## Dashboard (Phase 7)

`frontend/` is a React + Vite SPA consuming this API through the Vite dev proxy:

- **Dashboard page**: latest sensor cards (client-side colouring mirrors the rule-engine bands), Safety Rule verdict panel, Water Quality Score gauge, dual-verdict ML card (EXPERIMENTAL badge, confidence bar, automatic safety/ML disagreement highlight), Recharts trends.
- **History page**: 1h/6h/24h/7d ranges, auto-refresh, filterable readings table (safety, source, device, disagreements).
- **Settings page**: `GET`/`PUT /api/config` threshold editor, system health panel, latest stored ML verdict with disclaimer.
- **Mode badge**: `SIMULATION` vs `REAL HARDWARE` from the reading's `source`; `SIMULATION` is software-generated data, never real ESP32 readings.
- Polling (5 s/10 s) + inline API error banners; safety verdict always displayed as authoritative over ML.

## Architectural Decoupling Principles
1. **Rule Engine vs. ML**: The Rule Engine checks deterministic physical safety boundaries (e.g., pH < 6.5 or Turbidity > 5 NTU) while ML assesses empirical multi-parameter potability likelihood. If a reading is chemically non-compliant, the Safety Engine flags `UNSAFE` regardless of ML output.
2. **Pluggable Ingestion**: The API contract `{ device_id, ph, tds, turbidity, temperature, source }` is fixed. No frontend or ML changes are required when switching from simulation to hardware.

