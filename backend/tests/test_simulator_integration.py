"""
Phase 6 integration tests: real communication with the running backend.

Skipped automatically when the API is not reachable, so the unit suite never
depends on a live server.
"""
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulator.client import build_payload, post_reading  # noqa: E402
from simulator.scenarios import resolve_scenario  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"


def _server_reachable() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/health", timeout=3) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001 - skip when no server
        return False


pytestmark = pytest.mark.skipif(
    not _server_reachable(),
    reason="live API not running (start: uvicorn app.main:app --port 8000)",
)


def test_simulator_posts_reading_to_live_api():
    """A generated reading goes through the real POST /api/readings pipeline."""
    reading = resolve_scenario("normal").build_generator(seed=42).next_reading()
    payload = build_payload("PHASE6-SIM-LIVE", reading)

    result = post_reading(BASE_URL, payload, timeout=15)

    assert result.ok is True, result.error
    assert result.status == 201
    assert result.prediction in ("POTABLE", "NOT POTABLE")
    assert result.confidence is not None and 0.0 <= result.confidence <= 1.0
    assert result.safety_status in ("SAFE", "WARNING", "UNSAFE")
    assert 0.0 <= result.body["quality_score"] <= 100.0
    assert result.body["device_id"] == "PHASE6-SIM-LIVE"
    assert result.body["reading"]["source"] == "SIMULATION"


def test_live_cli_sends_counted_readings():
    """End-to-end CLI run against the live server (2 readings, no wait)."""
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "simulator" / "simulator.py"),
            "--scenario", "normal",
            "--count", "2",
            "--interval", "0",
            "--seed", "11",
            "--device-id", "PHASE6-SIM-CLI",
            "--base-url", BASE_URL,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.count(" 201  ") >= 2, completed.stdout
    assert "Finished: 2 reading(s) sent successfully." in completed.stdout
    assert "API error" not in completed.stdout


def test_live_cli_reports_api_errors():
    """Unreachable backend => errors are printed and the exit code is non-zero."""
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "simulator" / "simulator.py"),
            "--scenario", "recovery",
            "--count", "1",
            "--interval", "0",
            "--seed", "2",
            "--base-url", "http://127.0.0.1:9",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "API error" in completed.stdout
    assert "Finished with 1 reading(s), 1 API error(s)." in completed.stdout


def test_live_scenario_reading_range_and_persistence():
    """SENSOR_RECOVERY first sample is degraded, API still accepts and scores it."""
    generator = resolve_scenario("sensor_recovery").build_generator(seed=42)
    reading = generator.next_reading()
    assert reading.ph < 6.0 and reading.tds > 750.0

    result = post_reading(BASE_URL, build_payload("PHASE6-SIM-RECOVER", reading), timeout=15)
    assert result.ok is True, result.error
    assert result.body["safety_status"] in ("WARNING", "UNSAFE")
    # Rule engine (not ML) decided the status; ML verdict reported alongside
    assert result.prediction in ("POTABLE", "NOT POTABLE")
    assert 0.0 <= result.confidence <= 1.0
