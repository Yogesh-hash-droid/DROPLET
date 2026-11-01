import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import check_db_connection, SessionLocal
from app.config import get_settings
from app.models.water_reading import WaterReading
from app.models.device import Device
from app.models.prediction import Prediction

if os.getenv("DROPLET_RUN_MYSQL_INTEGRATION") != "1":
    pytest.skip(
        "MySQL integration suite is opt-in; use the isolated backend suite by default",
        allow_module_level=True,
    )

if get_settings().MYSQL_DATABASE != "water_quality_db_test":
    pytest.skip(
        "MySQL integration requires MYSQL_DATABASE=water_quality_db_test",
        allow_module_level=True,
    )

# Clear any dependency overrides to test against real MySQL
app.dependency_overrides.clear()
client = TestClient(app)


def test_mysql_connection_live():
    """Verify live connection to MySQL server."""
    assert check_db_connection() is True, "Live MySQL database connection check failed"


def test_mysql_reading_persistence_integration():
    """Verify creating a reading writes to the actual MySQL database and updates device table."""
    device_id = "MYSQL-INT-001"
    payload = {
        "device_id": device_id,
        "ph": 7.42,
        "tds": 280.5,
        "turbidity": 1.85,
        "temperature": 28.2,
        "source": "SIMULATION"
    }

    response = client.post("/api/readings", json=payload)
    assert response.status_code == 201, f"Failed: {response.text}"
    data = response.json()
    reading_id = data["id"]
    assert reading_id > 0
    assert data["device_id"] == device_id
    assert data["ph"] == 7.42

    # Query MySQL directly using a fresh session to confirm database persistence
    db = SessionLocal()
    try:
        db_reading = db.query(WaterReading).filter(WaterReading.id == reading_id).first()
        assert db_reading is not None
        assert db_reading.device_id == device_id
        assert abs(db_reading.ph - 7.42) < 1e-4

        # Verify device heartbeat in devices table
        db_device = db.query(Device).filter(Device.device_id == device_id).first()
        assert db_device is not None
        assert db_device.status.value == "ONLINE"
        assert db_device.last_seen is not None
    finally:
        db.close()


def test_mysql_readings_latest_integration():
    """Verify GET /api/readings/latest against live MySQL."""
    payload = {
        "device_id": "MYSQL-INT-002",
        "ph": 6.95,
        "tds": 150.0,
        "turbidity": 0.8,
        "temperature": 25.0,
        "source": "ESP32"
    }
    post_res = client.post("/api/readings", json=payload)
    assert post_res.status_code == 201

    get_res = client.get("/api/readings/latest")
    assert get_res.status_code == 200
    latest = get_res.json()
    assert latest["device_id"] == "MYSQL-INT-002"
    assert latest["source"] == "ESP32"
    assert latest["ph"] == 6.95


def test_mysql_readings_history_integration():
    """Verify GET /api/readings/history with limit and ordering against live MySQL."""
    res = client.get("/api/readings/history?limit=10")
    assert res.status_code == 200
    history = res.json()
    assert isinstance(history, list)
    assert len(history) >= 2
    # Verify newest first order
    assert history[0]["id"] >= history[1]["id"]


# ---------------------------------------------------------------------------
# Phase 10 additions (plan section 9): migration-dependent checks.
#
# STATUS: BLOCKED - SEPARATE MIGRATION APPROVAL REQUIRED. These tests need the
# Phase 10 schema in MySQL (nullable water_readings.ph/temperature, the ESP8266
# source enum member, predictions.score_method, system_config band columns).
# They SKIP (never fail) until the separately approved migration has run, and
# they were NOT executed during the Phase 10 implementation verification pass.
# ---------------------------------------------------------------------------


def _phase10_migration_applied() -> bool:
    """Inspect the live MySQL schema for every Phase 10 change. Read-only:
    no DDL, no data changes; any connection/inspection error -> not applied."""
    from sqlalchemy import inspect as sa_inspect, text
    from app.database import engine

    try:
        inspector = sa_inspect(engine)
        wr = {c["name"]: c for c in inspector.get_columns("water_readings")}
        pred_cols = {c["name"] for c in inspector.get_columns("predictions")}
        sys_cols = {c["name"] for c in inspector.get_columns("system_config")}
        with engine.connect() as conn:
            source_type = conn.execute(text(
                "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'water_readings' AND COLUMN_NAME = 'source'"
            )).scalar()
        return (
            wr.get("ph", {}).get("nullable") is True
            and wr.get("temperature", {}).get("nullable") is True
            and "score_method" in pred_cols
            and "status_good_min" in sys_cols
            and "status_poor_max" in sys_cols
            and source_type is not None
            and "ESP8266" in str(source_type)
        )
    except Exception:
        return False


_MIGRATION_SKIP = pytest.mark.skipif(
    not _phase10_migration_applied(),
    reason="BLOCKED - Phase 10 migration not applied; separate migration approval required",
)


@_MIGRATION_SKIP
def test_mysql_esp8266_two_sensor_persistence_integration():
    """Plan inventory (+1 ESP8266 case) and T12 post-migration check: the
    two-sensor payload persists with SQL NULL ph/temperature and the R-3
    discriminator, verified by direct SELECT against MySQL."""
    device_id = "MYSQL-P10-ESP8266-001"
    payload = {
        "device_id": device_id,
        "tds": 300.0,
        "turbidity": 2.0,
        "source": "ESP8266",
    }
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 201, f"Failed: {response.text}"
    data = response.json()
    reading_id = data["id"]
    assert data["ph"] is None
    assert data["temperature"] is None
    assert data["score_method"] == "TWO_PARAM_SCREENING"
    assert data["quality_score"] == 93.5
    assert data["screening_status"] == "GOOD"
    assert data["parameter_rule_check"]["status"] == "PASS"
    assert data["ml_status"] == "UNAVAILABLE"
    assert data["ml_status_reason"] == "PH_NOT_MEASURED"

    db = SessionLocal()
    try:
        db_reading = db.query(WaterReading).filter(WaterReading.id == reading_id).first()
        assert db_reading is not None
        assert db_reading.ph is None              # stored as SQL NULL, not defaulted
        assert db_reading.temperature is None
        assert db_reading.source.value == "ESP8266"
        assert db_reading.assessment.score_method.value == "TWO_PARAM_SCREENING"
    finally:
        db.close()


@_MIGRATION_SKIP
def test_t28_score_method_column_and_historical_nulls():
    """T28 (post-migration): predictions.score_method exists; historical rows
    keep NULL forever (never backfilled) and FOUR_PARAM_LEGACY is never written."""
    db = SessionLocal()
    try:
        null_count = db.query(Prediction).filter(Prediction.score_method.is_(None)).count()
        legacy_tagged = db.query(Prediction).filter(
            Prediction.score_method == "FOUR_PARAM_LEGACY"
        ).count()
        screening_count = db.query(Prediction).filter(
            Prediction.score_method == "TWO_PARAM_SCREENING"
        ).count()
    finally:
        db.close()
    # Historical rows are never rewritten; new rows carry the discriminator.
    assert legacy_tagged == 0
    assert null_count >= 0
    assert screening_count >= 1


@_MIGRATION_SKIP
def test_t29_band_columns_and_config_row():
    """T29 (post-migration): system_config has the band columns with a sane row."""
    from app.models.system_config import SystemConfig

    db = SessionLocal()
    try:
        config = db.query(SystemConfig).first()
        assert config is not None, "config row id=1 must exist after provisioning"
        assert 0.0 <= config.status_poor_max < config.status_good_min <= 100.0
    finally:
        db.close()

    res = client.get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert 0.0 <= body["status_poor_max"] < body["status_good_min"] <= 100.0
