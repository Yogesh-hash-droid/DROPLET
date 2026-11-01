import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db

# Isolated In-Memory SQLite database for unit tests
SQLITE_TEST_URL = "sqlite:///:memory:"
test_engine = create_engine(
    SQLITE_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


@pytest.fixture(autouse=True)
def setup_unit_db():
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _post_lax(client, path, payload):
    """POST raw lax JSON (stdlib json.dumps emits Infinity/NaN tokens, the same
    wire format as Python `requests`/raw-socket hardware clients; httpx's
    `json=` helper refuses them). Server-side rejection is what is under test."""
    import json
    return client.post(
        path,
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )


def test_valid_reading_unit(client):
    """Test 1: Valid water reading returns 201 Created and persisted values."""
    payload = {
        "device_id": "TEST-UNIT-001",
        "ph": 7.35,
        "tds": 240.0,
        "turbidity": 2.1,
        "temperature": 26.5,
        "source": "SIMULATION"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["device_id"] == "TEST-UNIT-001"
    assert data["ph"] == 7.35
    assert data["tds"] == 240.0
    assert data["turbidity"] == 2.1
    assert data["temperature"] == 26.5
    assert data["source"] == "SIMULATION"
    assert "id" in data
    assert "timestamp" in data


def test_invalid_ph_high_unit(client):
    """Test 2a: pH > 14 fails validation with 422 Unprocessable Entity."""
    payload = {
        "device_id": "TEST-UNIT-001",
        "ph": 15.0,
        "tds": 250.0,
        "turbidity": 2.0,
        "temperature": 25.0,
        "source": "SIMULATION"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 422


def test_invalid_ph_negative_unit(client):
    """Test 2b: pH < 0 fails validation with 422 Unprocessable Entity."""
    payload = {
        "device_id": "TEST-UNIT-001",
        "ph": -1.5,
        "tds": 250.0,
        "turbidity": 2.0,
        "temperature": 25.0,
        "source": "SIMULATION"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 422


def test_negative_tds_unit(client):
    """Test 3: Negative TDS fails validation with 422 Unprocessable Entity."""
    payload = {
        "device_id": "TEST-UNIT-001",
        "ph": 7.0,
        "tds": -10.0,
        "turbidity": 2.0,
        "temperature": 25.0,
        "source": "SIMULATION"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 422


def test_negative_turbidity_unit(client):
    """Test 4: Negative turbidity fails validation with 422 Unprocessable Entity."""
    payload = {
        "device_id": "TEST-UNIT-001",
        "ph": 7.0,
        "tds": 100.0,
        "turbidity": -0.5,
        "temperature": 25.0,
        "source": "SIMULATION"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 422


def test_invalid_source_unit(client):
    """Test 5: Unsupported source fails validation with 422 Unprocessable Entity."""
    payload = {
        "device_id": "TEST-UNIT-001",
        "ph": 7.0,
        "tds": 100.0,
        "turbidity": 1.0,
        "temperature": 25.0,
        "source": "BLUETOOTH_UNKNOWN"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 422


def test_latest_reading_unit(client):
    """Test 6: Retrieve most recent reading."""
    payload = {
        "device_id": "TEST-UNIT-LATEST",
        "ph": 8.0,
        "tds": 300.0,
        "turbidity": 1.5,
        "temperature": 24.0,
        "source": "ESP32"
    }
    post_res = client.post("/api/readings", json=payload)
    assert post_res.status_code == 201

    get_res = client.get("/api/readings/latest")
    assert get_res.status_code == 200
    latest_data = get_res.json()
    assert latest_data["device_id"] == "TEST-UNIT-LATEST"
    assert latest_data["source"] == "ESP32"


def test_history_endpoint_unit(client):
    """Test 7: Retrieve history with limit parameter ordered newest first."""
    get_res = client.get("/api/readings/history?limit=5")
    assert get_res.status_code == 200
    items = get_res.json()
    assert isinstance(items, list)
    assert len(items) >= 2
    # Verify newest first (descending IDs)
    assert items[0]["id"] >= items[1]["id"]


def test_boolean_tds_rejected_unit(client):
    """Phase 8: a JSON boolean must never be coerced into a sensor value."""
    payload = {
        "device_id": "TEST-UNIT-BOOL",
        "ph": 7.0,
        "tds": True,
        "turbidity": 1.0,
        "temperature": 25.0,
        "source": "SIMULATION"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 422


def test_boolean_ph_rejected_unit(client):
    """Phase 8: boolean pH is rejected too (all four numeric fields)."""
    payload = {
        "device_id": "TEST-UNIT-BOOL",
        "ph": False,
        "tds": 100.0,
        "turbidity": 1.0,
        "temperature": 25.0,
        "source": "SIMULATION"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 422


def test_integer_values_still_accepted_unit(client):
    """Phase 8: integers remain valid JSON numbers (no over-tightening)."""
    payload = {
        "device_id": "TEST-UNIT-INT",
        "ph": 7,
        "tds": 250,
        "turbidity": 2,
        "temperature": 25,
        "source": "SIMULATION"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["ph"] == 7.0
    assert data["tds"] == 250.0


# ---------------------------------------------------------------------------
# Phase 10 additions (plan section 8, Step 10 - extended coverage).
# The module-level database is shared, so these tests use unique device ids
# and are appended after the Phase 1-9 tests (they never assume an empty DB).
# ---------------------------------------------------------------------------

def test_esp8266_two_sensor_reading_unit(client):
    """ESP8266 hardware payload (tds + turbidity only) is accepted: 201 with
    NULL pH/temperature, the two-parameter assessment and ML skipped."""
    payload = {
        "device_id": "P10-UNIT-ESP8266-001",
        "tds": 300.0,
        "turbidity": 2.0,
        "source": "ESP8266"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()

    # Optional sensors are absent, never fabricated
    assert data["ph"] is None
    assert data["temperature"] is None
    assert data["reading"]["ph"] is None
    assert data["reading"]["temperature"] is None

    # Two-parameter screening: S_tds(300)=93.3333, S_turb(2.0)=93.75 -> 93.5208 -> 93.5 GOOD
    assert data["score_method"] == "TWO_PARAM_SCREENING"
    assert data["quality_score"] == 93.5
    assert data["screening_status"] == "GOOD"
    assert data["screening_explanation"]

    # Parameter Rule Check: TDS 300 <= 500 and turbidity 2.0 <= 5.0 -> PASS
    assert data["parameter_rule_check"]["status"] == "PASS"
    assert data["safety_status"] == "SAFE"          # DEPRECATED mirror only

    # ML is never invoked without pH: explicit unavailable reason, null verdict
    assert data["ml_status"] == "UNAVAILABLE"
    assert data["ml_status_reason"] == "PH_NOT_MEASURED"
    assert data["prediction"] is None
    assert data["confidence"] is None


def test_missing_tds_rejected_unit(client):
    """TDS is required (422), even for the ESP8266 two-sensor payload."""
    payload = {
        "device_id": "P10-UNIT-MISSING-TDS",
        "turbidity": 2.0,
        "source": "ESP8266"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 422


def test_optional_ph_temperature_stored_as_null_unit(client):
    """Absent pH/temperature are persisted as SQL NULL (verified directly)."""
    from app.models.water_reading import WaterReading

    payload = {
        "device_id": "P10-UNIT-NULL-STORE",
        "tds": 260.0,
        "turbidity": 1.4,
        "source": "ESP8266"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 201, response.text
    reading_id = response.json()["reading_id"]

    db = TestingSessionLocal()
    try:
        row = db.query(WaterReading).filter(WaterReading.id == reading_id).first()
        assert row is not None
        assert row.ph is None
        assert row.temperature is None
    finally:
        db.close()


def test_hardware_reading_uses_two_parameter_rule_check_unit(client):
    """A WARNING band breach surfaces in the primary vocabulary with the
    deprecated mirror mapping WARNING -> WARNING."""
    payload = {
        "device_id": "P10-UNIT-ESP8266-002",
        "tds": 650.0,       # WARNING: > 500 but <= 750
        "turbidity": 1.5,   # PASS
        "source": "ESP8266"
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["parameter_rule_check"]["status"] == "WARNING"
    assert data["safety_status"] == "WARNING"
    assert data["safety"]["status"] == "WARNING"
    assert data["safety"]["violated_parameters"] == ["TDS"]
    assert "Parameter Rule Check" in data["parameter_rule_check"]["label"]
    assert "does NOT certify" in data["parameter_rule_check"]["disclaimer"]
    assert "Laboratory testing is required" in data["parameter_rule_check"]["disclaimer"]


# ---------------------------------------------------------------------------
# Phase 10 non-finite input fix: +/-Infinity and NaN are never valid
# measurements (422), and a rejected request creates no database record.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "field,value",
    [
        ("tds", float("inf")), ("tds", float("-inf")), ("tds", float("nan")),
        ("turbidity", float("inf")), ("turbidity", float("-inf")), ("turbidity", float("nan")),
    ],
    ids=[
        "tds-pos-inf", "tds-neg-inf", "tds-nan",
        "turbidity-pos-inf", "turbidity-neg-inf", "turbidity-nan",
    ],
)
def test_non_finite_required_values_rejected_unit(client, field, value):
    """Non-finite required measurements -> 422 (+Infinity previously slipped
    through ge=0.0 and failed with HTTP 500)."""
    payload = {"device_id": f"P10-NF-{field}", "tds": 300.0, "turbidity": 2.0, "source": "ESP8266"}
    payload[field] = value
    response = _post_lax(client, "/api/readings", payload)
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], list)  # body stays valid JSON


@pytest.mark.parametrize(
    "field,value",
    [
        ("ph", float("inf")), ("ph", float("nan")),
        ("temperature", float("inf")), ("temperature", float("-inf")), ("temperature", float("nan")),
    ],
    ids=["ph-pos-inf", "ph-nan", "temp-pos-inf", "temp-neg-inf", "temp-nan"],
)
def test_non_finite_optional_values_rejected_unit(client, field, value):
    """Optional sensors are rejected when SUPPLIED as non-finite - optional
    means nullable, not unvalidated."""
    payload = {"device_id": f"P10-NF-{field}", "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}
    payload[field] = value
    response = _post_lax(client, "/api/readings", payload)
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], list)


def test_rejected_non_finite_creates_no_record_unit(client):
    """After a rejected non-finite ingestion no reading/assessment is persisted
    (row count unchanged in the shared unit database)."""
    from app.models.prediction import Prediction
    from app.models.water_reading import WaterReading

    db = TestingSessionLocal()
    try:
        readings_before = db.query(WaterReading).count()
        predictions_before = db.query(Prediction).count()
    finally:
        db.close()

    response = _post_lax(
        client,
        "/api/readings",
        {"device_id": "P10-NF-PERSIST", "tds": float("inf"), "turbidity": float("nan"), "source": "ESP8266"},
    )
    assert response.status_code == 422

    db = TestingSessionLocal()
    try:
        assert db.query(WaterReading).count() == readings_before
        assert db.query(Prediction).count() == predictions_before
    finally:
        db.close()
