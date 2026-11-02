"""
Tests for Arduino Uno hardware support (source=ARDUINO_UNO).

Acceptance checks from section 7 of the conversion brief:
  [AC1] Old payload with pH and temperature still returns success.
  [AC2] Arduino Uno payload (no pH, no temp, source=ARDUINO_UNO) is accepted and stored.
  [AC3] Invalid payloads (non-numeric TDS, negative turbidity, unknown source) return 4xx.
  [AC4] Gateway validation logic correctly filters bad lines.
"""

import json
import math
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Schema-level unit tests (no DB required)
# ─────────────────────────────────────────────────────────────────────────────
from pydantic import ValidationError
from app.schemas.water_reading import WaterReadingCreate


class TestWaterReadingSchema:
    """[AC1] Backward compatibility — old payloads still validate."""

    def test_full_payload_with_ph_and_temp_validates(self):
        """Old ESP8266/SIMULATION payload with all four sensors must still be valid."""
        data = WaterReadingCreate(
            device_id="SIM-001",
            tds=250.0,
            turbidity=2.5,
            ph=7.2,
            temperature=22.0,
            source="SIMULATION",
            sensor_status="ok",
        )
        assert data.ph == 7.2
        assert data.temperature == 22.0

    """[AC2] Arduino Uno payload without pH and temperature must validate."""

    def test_arduino_uno_payload_without_ph_temp_validates(self):
        data = WaterReadingCreate(
            device_id="UNO-001",
            tds=250.0,
            turbidity=3.5,
            source="ARDUINO_UNO",
            sensor_status="ok",
        )
        assert data.source == "ARDUINO_UNO"
        assert data.ph is None
        assert data.temperature is None

    def test_arduino_uno_minimal_payload(self):
        """Only device_id, tds, turbidity, source are required for Uno."""
        data = WaterReadingCreate(
            device_id="UNO-001",
            tds=0.0,
            turbidity=0.5,
            source="ARDUINO_UNO",
        )
        assert data.tds == 0.0

    """[AC3] Invalid payloads must be rejected."""

    def test_unknown_source_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            WaterReadingCreate(
                device_id="X-001",
                tds=100.0,
                turbidity=1.0,
                source="RASPBERRY_PI",
            )
        assert "source" in str(exc_info.value).lower()

    def test_negative_tds_rejected(self):
        with pytest.raises(ValidationError):
            WaterReadingCreate(
                device_id="UNO-001",
                tds=-10.0,
                turbidity=1.0,
                source="ARDUINO_UNO",
            )

    def test_negative_turbidity_rejected(self):
        with pytest.raises(ValidationError):
            WaterReadingCreate(
                device_id="UNO-001",
                tds=100.0,
                turbidity=-5.0,
                source="ARDUINO_UNO",
            )

    def test_non_numeric_tds_rejected(self):
        with pytest.raises(ValidationError):
            WaterReadingCreate(
                device_id="UNO-001",
                tds="not_a_number",  # type: ignore[arg-type]
                turbidity=1.0,
                source="ARDUINO_UNO",
            )

    def test_infinite_tds_rejected(self):
        with pytest.raises(ValidationError):
            WaterReadingCreate(
                device_id="UNO-001",
                tds=math.inf,
                turbidity=1.0,
                source="ARDUINO_UNO",
            )

    def test_boolean_tds_rejected(self):
        """Booleans must not be silently coerced to 0.0 or 1.0."""
        with pytest.raises(ValidationError):
            WaterReadingCreate(
                device_id="UNO-001",
                tds=True,  # type: ignore[arg-type]
                turbidity=1.0,
                source="ARDUINO_UNO",
            )

    def test_ph_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            WaterReadingCreate(
                device_id="UNO-001",
                tds=100.0,
                turbidity=1.0,
                ph=15.0,           # > 14.0
                source="ARDUINO_UNO",
            )

    def test_all_allowed_sources_accepted(self):
        for src in ("SIMULATION", "ESP32", "ESP8266", "ARDUINO_UNO"):
            d = WaterReadingCreate(
                device_id="TEST-001",
                tds=100.0,
                turbidity=1.0,
                source=src,
            )
            assert d.source == src

    def test_sensor_status_serial_fault_accepted(self):
        """Arduino Uno gateway can send serial_fault as sensor_status."""
        d = WaterReadingCreate(
            device_id="UNO-001",
            tds=None,
            turbidity=None,
            source="ARDUINO_UNO",
            sensor_status="serial_fault",
        )
        assert d.sensor_status == "serial_fault"
        assert d.tds is None

    def test_tds_required_when_sensor_ok(self):
        """When sensor_status='ok', tds must be present."""
        with pytest.raises(ValidationError):
            WaterReadingCreate(
                device_id="UNO-001",
                tds=None,
                turbidity=1.0,
                source="ARDUINO_UNO",
                sensor_status="ok",
            )


# ─────────────────────────────────────────────────────────────────────────────
# Gateway validation unit tests (no serial port, no network)
# ─────────────────────────────────────────────────────────────────────────────
import importlib.util, pathlib

_GATEWAY_PATH = pathlib.Path(__file__).parent.parent.parent / "arduino" / "gateway.py"


def _load_gateway():
    """Dynamically import arduino/gateway.py without running main()."""
    spec = importlib.util.spec_from_file_location("arduino_gateway", _GATEWAY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gw():
    if not _GATEWAY_PATH.exists():
        pytest.skip("arduino/gateway.py not found — skipping gateway tests")
    return _load_gateway()


class TestGatewayValidation:
    """[AC4] Gateway validate_reading() filters bad lines correctly."""

    def test_valid_uno_reading_passes(self, gw):
        ok, reason = gw.validate_reading({
            "device_id": "UNO-001",
            "tds": 250.0,
            "turbidity": 3.5,
            "source": "ARDUINO_UNO",
        })
        assert ok is True
        assert reason == ""

    def test_missing_tds_rejected(self, gw):
        ok, reason = gw.validate_reading({
            "device_id": "UNO-001",
            "turbidity": 3.5,
        })
        assert ok is False
        assert "tds" in reason.lower()

    def test_non_numeric_tds_rejected(self, gw):
        ok, reason = gw.validate_reading({
            "device_id": "UNO-001",
            "tds": "bad",
            "turbidity": 3.5,
        })
        assert ok is False

    def test_negative_turbidity_rejected(self, gw):
        ok, reason = gw.validate_reading({
            "device_id": "UNO-001",
            "tds": 100.0,
            "turbidity": -1.0,
        })
        assert ok is False
        assert "turbidity" in reason.lower()

    def test_missing_device_id_rejected(self, gw):
        ok, reason = gw.validate_reading({
            "tds": 100.0,
            "turbidity": 1.0,
        })
        assert ok is False
        assert "device_id" in reason.lower()

    def test_inf_tds_rejected(self, gw):
        ok, reason = gw.validate_reading({
            "device_id": "UNO-001",
            "tds": math.inf,
            "turbidity": 1.0,
        })
        assert ok is False

    def test_zero_values_valid(self, gw):
        """Probe in air reads 0 ppm TDS — that is a valid (not fake) measurement."""
        ok, _ = gw.validate_reading({
            "device_id": "UNO-001",
            "tds": 0.0,
            "turbidity": 0.0,
        })
        assert ok is True
