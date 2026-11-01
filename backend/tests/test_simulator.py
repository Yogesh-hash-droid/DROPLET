"""
Phase 6 simulator tests: sensor generation, scenarios, CLI and API payload.

Unit-level only - no live server required (HTTP transport is stubbed).
`tests/test_simulator_integration.py` covers real API communication.
"""
import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulator import client  # noqa: E402
from simulator.client import ApiResponse, build_payload, post_reading  # noqa: E402
from simulator.scenarios import ALIASES, SCENARIOS, resolve_scenario  # noqa: E402
from simulator.sensors import PHYSICAL_BOUNDS, SENSOR_NAMES  # noqa: E402
from simulator.simulator import format_row, parse_args  # noqa: E402

EXPECTED_KEYS = [
    "NORMAL",
    "PH_DRIFT_LOW",
    "PH_DRIFT_HIGH",
    "HIGH_TDS",
    "HIGH_TURBIDITY",
    "ACIDIC_WATER",
    "ALKALINE_WATER",
    "TEMPERATURE_SPIKE",
    "MULTIPLE_PROBLEM",
    "SENSOR_RECOVERY",
]


def _values(rows, name):
    return [getattr(row, name) for row in rows]


def _first_tick(rows, name, predicate):
    for index, row in enumerate(rows):
        if predicate(getattr(row, name)):
            return index
    return None


# ------------------------------------------------------------ generation -----
def test_normal_generation_ranges():
    """NORMAL stays inside realistic domestic tap-water ranges."""
    rows = resolve_scenario("normal").build_generator(seed=42).history(60)
    assert len(rows) == 60
    assert all(6.5 <= r.ph <= 8.5 for r in rows)
    assert all(100.0 <= r.tds <= 400.0 for r in rows)
    assert all(0.2 <= r.turbidity <= 4.0 for r in rows)
    assert all(20.0 <= r.temperature <= 35.0 for r in rows)


def test_values_respect_physical_and_schema_bounds_all_scenarios():
    """Every scenario stays inside physical/API-schema bounds at every tick."""
    for key in EXPECTED_KEYS:
        rows = resolve_scenario(key).build_generator(seed=7).history(60)
        for row in rows:
            for name in SENSOR_NAMES:
                low, high = PHYSICAL_BOUNDS[name]
                value = getattr(row, name)
                assert low <= value <= high, f"{key}/{name}={value} out of bounds"


def test_deterministic_seed_reproducible():
    """Same seed + scenario => identical sequence; different seed => different."""
    first = resolve_scenario("normal").build_generator(seed=123).history(25)
    second = resolve_scenario("normal").build_generator(seed=123).history(25)
    third = resolve_scenario("normal").build_generator(seed=124).history(25)
    assert first == second
    assert first != third

    a = resolve_scenario("acidic").build_generator(seed=5).history(15)
    b = resolve_scenario("acidic").build_generator(seed=5).history(15)
    assert a == b


def test_gradual_changes_no_unrealistic_jumps():
    """Per-tick deltas are clamped - no 7.1 -> 12.9 -> 3.2 style jumps."""
    # channel max_step plus a small allowance for output rounding (2 dp / 1 dp)
    limits = {"ph": 0.14, "tds": 45.2, "turbidity": 0.72, "temperature": 1.52}
    for key in EXPECTED_KEYS:
        rows = resolve_scenario(key).build_generator(seed=42).history(70)
        for previous, current in zip(rows, rows[1:]):
            for name, limit in limits.items():
                delta = abs(getattr(current, name) - getattr(previous, name))
                assert delta <= limit + 1e-9, f"{key}/{name} jumped {delta}"


def test_normal_scenario_has_no_safety_threshold_crossings():
    """NORMAL never breaches the default safety thresholds."""
    rows = resolve_scenario("normal").build_generator(seed=42).history(60)
    for row in rows:
        assert 6.5 <= row.ph <= 8.5
        assert row.tds <= 500.0
        assert row.turbidity <= 5.0
        assert 10.0 <= row.temperature <= 35.0


# ------------------------------------------------------------- scenarios -----
def test_all_ten_scenarios_registered_with_aliases():
    assert sorted(SCENARIOS) == sorted(EXPECTED_KEYS)
    for alias in ("normal", "high_tds", "acidic", "multiple_problem", "recovery", "NORMAL"):
        assert resolve_scenario(alias).key == ALIASES[alias.lower()]


def test_resolve_unknown_scenario_rejected():
    with pytest.raises(KeyError):
        resolve_scenario("not_a_scenario")


@pytest.mark.parametrize("key", EXPECTED_KEYS)
def test_each_scenario_behaviour(key):
    """Each scenario does what its documentation promises."""
    rows = resolve_scenario(key).build_generator(seed=42).history(90)
    first, last = rows[0], rows[-1]

    if key == "NORMAL":
        assert all(6.5 <= r.ph <= 8.5 for r in rows)
        assert all(r.tds <= 500 for r in rows)
    elif key == "PH_DRIFT_LOW":
        assert _first_tick(rows, "ph", lambda v: v < 6.5) is not None
        assert last.ph < 6.0
        assert last.ph < first.ph - 1.0
    elif key == "PH_DRIFT_HIGH":
        assert _first_tick(rows, "ph", lambda v: v > 8.5) is not None
        assert last.ph > 9.0
    elif key == "HIGH_TDS":
        assert _first_tick(rows, "tds", lambda v: v > 500) is not None
        assert last.tds > 750
        assert all(r.ph == pytest.approx(first.ph, abs=0.6) for r in rows)
    elif key == "HIGH_TURBIDITY":
        assert _first_tick(rows, "turbidity", lambda v: v > 5) is not None
        assert last.turbidity > 10
    elif key == "ACIDIC_WATER":
        assert _first_tick(rows, "ph", lambda v: v < 6.0) is not None
        assert last.ph < 5.0
    elif key == "ALKALINE_WATER":
        assert _first_tick(rows, "ph", lambda v: v > 9.0) is not None
        assert last.ph > 10.0
    elif key == "TEMPERATURE_SPIKE":
        peak = max(_values(rows, "temperature"))
        assert peak > 40.0, "spike must reach the UNSAFE band"
        assert last.temperature < 35.0, "spike must recover"
        assert last.temperature < peak - 3.0
        assert all(6.5 <= r.ph <= 8.5 for r in rows)
    elif key == "MULTIPLE_PROBLEM":
        unsafe = sum([
            last.ph < 6.0,
            last.tds > 750.0,
            last.turbidity > 10.0,
        ])
        assert unsafe >= 3, f"expected >=3 unsafe parameters, got {unsafe}"
        assert last.temperature > 35.0
    elif key == "SENSOR_RECOVERY":
        assert first.ph < 6.0 and first.tds > 750.0 and first.turbidity > 5.0
        assert 6.5 <= last.ph <= 8.5
        assert last.tds < 500.0
        assert last.turbidity < 5.0
        assert last.temperature < 35.0
        assert last.tds < first.tds - 400.0


# -------------------------------------------------------------------- CLI ----
def test_cli_defaults():
    args = parse_args([])
    assert args.scenario == "normal"
    assert args.interval == 5.0
    assert args.device_id == "SIMULATOR-001"
    assert args.count is None
    assert args.seed is None
    assert args.dry_run is False
    assert args.base_url.startswith("http")


def test_cli_arguments_from_spec():
    args = parse_args(["--scenario", "high_tds", "--interval", "3", "--count", "20"])
    assert args.scenario == "high_tds"
    assert resolve_scenario(args.scenario).key == "HIGH_TDS"
    assert args.interval == 3.0
    assert args.count == 20

    args = parse_args(["--scenario", "acidic", "--device-id", "SIM-42", "--seed", "9"])
    assert resolve_scenario(args.scenario).key == "ACIDIC_WATER"
    assert args.device_id == "SIM-42"
    assert args.seed == 9

    args = parse_args(["--scenario", "multiple_problem", "--count", "1"])
    assert resolve_scenario(args.scenario).key == "MULTIPLE_PROBLEM"

    args = parse_args(["--scenario", "normal", "--interval", "0", "--dry-run"])
    assert args.interval == 0.0
    assert args.dry_run is True


def test_cli_invalid_arguments_rejected():
    with pytest.raises(SystemExit) as invalid_scenario:
        parse_args(["--scenario", "underwater_circus"])
    assert invalid_scenario.value.code == 2

    with pytest.raises(SystemExit) as invalid_count:
        parse_args(["--count", "0"])
    assert invalid_count.value.code == 2

    with pytest.raises(SystemExit) as invalid_interval:
        parse_args(["--interval", "-1"])
    assert invalid_interval.value.code == 2


def test_cli_end_to_end_dry_run():
    """Full CLI run (no server needed): header + exactly `count` data rows."""
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "simulator" / "simulator.py"),
            "--scenario", "acidic",
            "--count", "3",
            "--interval", "0",
            "--seed", "7",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    header = [line for line in lines if line.startswith("STEP")]
    rows = [line for line in lines if line.startswith("   0") or line.startswith("   1") or line.startswith("   2")]
    assert len(header) == 1
    assert len(rows) == 3, completed.stdout
    assert "SCENARIO" in header[0] and "HTTP" in header[0]
    assert "ACIDIC_WATER" in completed.stdout
    assert "not ESP32" in completed.stdout or "SIMULATION" in completed.stdout


# --------------------------------------------------------------- API payload -
def test_api_payload_format():
    """Payload matches the exact ESP32 JSON contract."""
    reading = resolve_scenario("normal").build_generator(seed=1).next_reading()
    payload = build_payload("SIMULATOR-001", reading)

    assert set(payload) == {"device_id", "ph", "tds", "turbidity", "temperature", "source"}
    assert payload["device_id"] == "SIMULATOR-001"
    assert payload["source"] == "SIMULATION"
    assert isinstance(payload["ph"], float)
    assert isinstance(payload["tds"], float)
    assert isinstance(payload["turbidity"], float)
    assert isinstance(payload["temperature"], float)
    assert 0.0 <= payload["ph"] <= 14.0
    assert payload["tds"] >= 0.0
    assert payload["turbidity"] >= 0.0
    assert -10.0 <= payload["temperature"] <= 100.0
    # JSON round-trip is stable
    assert json.loads(json.dumps(payload)) == payload


def test_payload_source_always_simulation():
    for key in EXPECTED_KEYS:
        generator = resolve_scenario(key).build_generator(seed=3)
        for reading in generator.history(5):
            assert build_payload("SIMULATOR-001", reading)["source"] == "SIMULATION"
    with pytest.raises(ValueError):
        build_payload("", resolve_scenario("normal").build_generator(seed=1).next_reading())


def test_format_row_contains_required_fields():
    reading = resolve_scenario("normal").build_generator(seed=1).next_reading()
    response = ApiResponse(
        status=201,
        ok=True,
        body={"prediction": "POTABLE", "confidence": 0.5677, "safety_status": "SAFE"},
    )
    row = format_row(0, "2026-10-06T12:00:00", "SIMULATOR-001", "NORMAL", reading, response)
    assert "SIMULATOR-001" in row
    assert "NORMAL" in row
    assert "201" in row
    assert "POTABLE" in row
    assert "0.568" in row
    assert "SAFE" in row


# ------------------------------------------------------ API error handling ----
class _FakeResponse:
    def __init__(self, payload, status=201):
        self._payload = payload
        self.status = status

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_api_success_parsing(monkeypatch):
    body = {"prediction": "NOT POTABLE", "confidence": 0.57, "safety_status": "SAFE"}
    monkeypatch.setattr(client, "_urlopen", lambda request, timeout: _FakeResponse(body))
    reading = resolve_scenario("normal").build_generator(seed=1).next_reading()
    result = post_reading("http://127.0.0.1:8000", build_payload("SIM-1", reading))

    assert result.ok is True
    assert result.status == 201
    assert result.prediction == "NOT POTABLE"
    assert result.confidence == 0.57
    assert result.safety_status == "SAFE"
    assert result.detail is None


def test_api_error_connection_refused(monkeypatch):
    def _refused(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(client, "_urlopen", _refused)
    reading = resolve_scenario("normal").build_generator(seed=1).next_reading()
    result = post_reading("http://127.0.0.1:1", build_payload("SIM-1", reading))

    assert result.ok is False
    assert result.status is None
    assert result.error and "connection refused" in result.error
    assert result.detail  # error is surfaced, never hidden
    assert result.prediction is None


def test_api_error_http_status(monkeypatch):
    def _http_error(request, timeout):
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8000/api/readings",
            code=422,
            msg="Unprocessable Entity",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"validation error"}'),
        )

    monkeypatch.setattr(client, "_urlopen", _http_error)
    reading = resolve_scenario("normal").build_generator(seed=1).next_reading()
    result = post_reading("http://127.0.0.1:8000", build_payload("SIM-1", reading))

    assert result.ok is False
    assert result.status == 422
    assert "422" in result.error
    assert result.detail is not None
