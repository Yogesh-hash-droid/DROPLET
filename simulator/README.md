# Water Quality Telemetry Simulator (Phase 6)

Realistic multi-scenario simulator that behaves like the future ESP32 sensor
node: it generates `ph`, `tds`, `turbidity` and `temperature` values and
continuously POSTs them to the live backend.

> **`SIMULATION` = software-generated sensor data.** It is **not** real ESP32
> hardware data. Every reading carries `"source": "SIMULATION"`, and the real
> firmware (later phase) will use `"source": "ESP32"` with the exact same JSON
> contract.

All safety evaluation, Water Quality Score calculation and ML inference happen
in the backend - the simulator **never** bypasses `POST /api/readings` and
never computes safety or predictions itself.

## How the sensor model works

Each channel keeps a live value that moves **gradually** towards a
scenario-defined target:

| Ingredient | Behaviour |
| --- | --- |
| Baseline | Healthy tap-water reference (pH 7.1, TDS 215 ppm, turbidity 1.4 NTU, 26.5 °C) |
| Noise | Small gaussian jitter every tick |
| Mean reversion | Value is pulled back towards the current target (and back to baseline after an event) |
| Drift | Scenarios move the *target* over time (ramps), so the value follows slowly |
| Events | `NORMAL` occasionally produces a small bump that heals itself |
| Delta clamp | Per-tick change is hard-limited (pH ≤ 0.12, TDS ≤ 45 ppm, turbidity ≤ 0.7 NTU, temp ≤ 1.5 °C) - no `7.1 → 12.9 → 3.2` jumps |
| Bounds | Clamped to physical/API ranges (pH 0-14, TDS ≥ 0, turbidity ≥ 0, temp -10…100 °C) |

Reproducible: `--seed N` makes a run bit-for-bit repeatable.

## Scenarios

| # | Scenario | CLI names | Documented behaviour |
| --- | --- | --- | --- |
| 1 | `NORMAL` | `normal` | Healthy tap water, all sensors around baseline with noise and rare self-recovering bumps. Stays SAFE for the whole run. |
| 2 | `PH_DRIFT_LOW` | `ph_drift_low`, `drift_low`, `low_ph` | pH drifts 7.1 → 5.8 over ~25 ticks: crosses WARNING (<6.5) at ~tick 21, UNSAFE (<6.0) at ~tick 37. Other sensors normal. |
| 3 | `PH_DRIFT_HIGH` | `ph_drift_high`, `drift_high`, `high_ph` | pH drifts 7.1 → 9.6: WARNING (>8.5) at ~tick 22, UNSAFE (>9.0) at ~tick 29. |
| 4 | `HIGH_TDS` | `high_tds`, `tds` | TDS climbs 230 → 900 ppm: WARNING (>500) at ~tick 16, UNSAFE (>750) at ~tick 26. |
| 5 | `HIGH_TURBIDITY` | `high_turbidity`, `high_turb`, `turbidity` | Turbidity rises 1.5 → 12 NTU: WARNING (>5) at ~tick 13, UNSAFE (>10) at ~tick 25. |
| 6 | `ACIDIC_WATER` | `acidic`, `acidic_water`, `acid` | Strongly acidic water: pH 7.0 → 4.5 in ~14 ticks (UNSAFE <6.0), TDS/turbidity rise slightly. |
| 7 | `ALKALINE_WATER` | `alkaline`, `alkaline_water`, `base` | Strongly alkaline water: pH 7.4 → 10.2 (UNSAFE >9.0). |
| 8 | `TEMPERATURE_SPIKE` | `temperature_spike`, `temp_spike`, `temperature` | Thermal event: 26.5 → ~43 °C (WARNING >35, UNSAFE >40), then decays back to baseline - a spike **with recovery**. Temperature is not an ML feature, so ML/safety disagreement is expected here. |
| 9 | `MULTIPLE_PROBLEM` | `multiple_problem`, `multiple`, `multi` | Simultaneous contamination: pH → 5.6, TDS → 850, turbidity → 11, temp → 38 °C. Three UNSAFE parameters plus a temperature warning; score drops sharply. |
| 10 | `SENSOR_RECOVERY` | `sensor_recovery`, `recovery`, `recover` | Starts degraded (pH 5.2, TDS 850, turbidity 9.5, 38 °C - several violations) and recovers to healthy baselines over ~20 ticks: violations clear and the score climbs. |

Thresholds used above are the **default** configuration
(`ph 6.5–8.5`, `tds_max 500`, `turbidity_max 5`, `temp 10–35 °C`;
moderate → WARNING, severe → UNSAFE) and can be changed at runtime via
`PUT /api/config`.

## CLI

```bash
# from the repository root (or from inside simulator/)
python simulator/simulator.py --scenario normal
python simulator/simulator.py --scenario high_tds --interval 3 --count 20
python simulator/simulator.py --scenario acidic --device-id SIMULATOR-002
python simulator/simulator.py --scenario multiple_problem --seed 42
python simulator/simulator.py --scenario recovery --interval 1 --count 10

# offline preview (no API calls)
python simulator/simulator.py --scenario temperature_spike --dry-run --count 5 --interval 0
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--scenario` | `normal` | scenario to run (see table above; case-insensitive) |
| `--interval` | `5.0` | seconds between readings |
| `--device-id` | `SIMULATOR-001` | `device_id` sent to the API |
| `--count` | *(none)* | number of readings; omit for continuous operation |
| `--seed` | *(none)* | random seed for reproducible sequences |
| `--base-url` | `http://127.0.0.1:8000` | backend base URL |
| `--timeout` | `10.0` | HTTP timeout in seconds |
| `--dry-run` | off | generate/print without calling the API |

Continuous mode runs until **Ctrl+C**. Exit code is `0` when every reading was
accepted and `1` if any API call failed (errors are printed, never hidden).

## Sample output

```
Scenario   : MULTIPLE_PROBLEM
Details    : Simultaneous contamination: pH drifts to 5.6, TDS to 850 ppm, ...
Device     : SIMULATOR-001  (source: SIMULATION - software data, not ESP32)
Target     : http://127.0.0.1:8000/api/readings
Interval   : 0.0s   Seed: 42
6 reading(s)
STEP  TIME                 DEVICE            SCENARIO              PH      TDS   TURB   TEMP  HTTP  PREDICTION     CONF  SAFETY
   0  2026-10-07T01:30:31  SIMULATOR-001     MULTIPLE_PROBLEM    7.09    215.5   1.40   26.6   201  POTABLE       0.568  SAFE
   1  2026-10-07T01:30:31  SIMULATOR-001     MULTIPLE_PROBLEM    7.07    211.4   1.49   26.6   201  POTABLE       0.573  SAFE
   2  2026-10-07T01:30:32  SIMULATOR-001     MULTIPLE_PROBLEM    7.04    220.8   1.62   26.9   201  POTABLE       0.576  SAFE
   ...
   5  2026-10-07T01:30:32  SIMULATOR-001     MULTIPLE_PROBLEM    6.99    260.2   2.10   27.4   201  POTABLE       0.539  SAFE

Finished: 6 reading(s) sent successfully.
```

Failures are shown inline, e.g. `!! API error: HTTP 500: ...` or
`!! API error: URLError: connection refused`.

## API payload (identical to the future ESP32 contract)

```json
{
  "device_id": "SIMULATOR-001",
  "ph": 7.1,
  "tds": 215.5,
  "turbidity": 1.4,
  "temperature": 26.6,
  "source": "SIMULATION"
}
```

Sent as `POST <base-url>/api/readings` with `Content-Type: application/json`.

## Layout

```
simulator/
├── simulator.py   # CLI entry point (loop, formatting, exit codes)
├── sensors.py     # reusable sensor generator (baseline/noise/drift/events)
├── scenarios.py   # the 10 scenarios and their documented behaviour
├── client.py      # POST /api/readings client (errors become data)
└── README.md
```

## Tests

Run from `backend/`:

```bash
python -m pytest tests/test_simulator.py tests/test_simulator_integration.py -q
```

- `tests/test_simulator.py` - unit tests (no server needed): generation
  ranges, physical/schema bounds for every scenario, deterministic seeds,
  gradual-change limits, all 10 scenarios' behaviour, CLI defaults/arguments/
  validation, a full CLI `--dry-run` subprocess run, API payload format,
  `source == SIMULATION`, and error handling with a stubbed transport.
- `tests/test_simulator_integration.py` - real API communication; skipped
  automatically when the backend is not running.
