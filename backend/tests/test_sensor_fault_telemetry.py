import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models.water_reading import WaterReading
from app.models.device import Device, DeviceStatus


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield TestingSessionLocal
    engine.dispose()


@pytest.fixture()
def client(db):
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db()
    with TestClient(app) as c:
        yield c
    if previous:
        app.dependency_overrides[get_db] = previous
    else:
        app.dependency_overrides.pop(get_db, None)


def test_sensor_fault_ads1115_not_found(client, db):
    """When ADS1115 fails to ACK, firmware transmits sensor_status='ads1115_not_found'
    with null sensor values. The backend must ingest the packet (201), set device ONLINE,
    store sensor_status, skip ML, and report UNAVAILABLE quality."""
    payload = {
        "device_id": "ESP8266-WATER-001",
        "source": "ESP8266",
        "sensor_status": "ads1115_not_found",
        "tds": None,
        "turbidity": None,
        "wifi_rssi": -65,
        "uptime": 12,
        "firmware_version": "4.2.0"
    }
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()

    assert data["device_id"] == "ESP8266-WATER-001"
    assert data["tds"] is None
    assert data["turbidity"] is None
    assert data["quality_score"] is None
    assert data["screening_status"] == "UNAVAILABLE"
    assert "ADS1115 not found" in data["screening_explanation"]
    assert data["ml_status"] == "UNAVAILABLE"
    assert data["ml_status_reason"] == "SENSOR_FAULT"
    assert data["reading"]["sensor_status"] == "ads1115_not_found"
    assert data["reading"]["wifi_rssi"] == -65
    assert data["reading"]["uptime"] == 12

    # Verify device status in DB is ONLINE
    session = db()
    try:
        device = session.query(Device).filter(Device.device_id == "ESP8266-WATER-001").first()
        assert device is not None
        assert device.status == DeviceStatus.ONLINE
        assert device.sensor_status == "ads1115_not_found"
        assert device.wifi_rssi == -65
        assert device.firmware_version == "4.2.0"

        # Verify reading stored in DB
        reading = session.query(WaterReading).filter(WaterReading.device_id == "ESP8266-WATER-001").first()
        assert reading is not None
        assert reading.sensor_status == "ads1115_not_found"
        assert reading.tds is None
        assert reading.turbidity is None
    finally:
        session.close()


def test_sensor_fault_read_error(client, db):
    """When I2C communication fails during conversion, firmware sends sensor_status='read_error'."""
    payload = {
        "device_id": "ESP8266-WATER-001",
        "source": "ESP8266",
        "sensor_status": "read_error",
        "tds": None,
        "turbidity": None,
        "wifi_rssi": -70,
        "uptime": 45,
        "firmware_version": "4.2.0"
    }
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["screening_status"] == "UNAVAILABLE"
    assert data["reading"]["sensor_status"] == "read_error"


def test_normal_telemetry_with_sensor_ok(client, db):
    """When sensor is ok, valid TDS and turbidity are processed with full screening."""
    payload = {
        "device_id": "ESP8266-WATER-001",
        "source": "ESP8266",
        "sensor_status": "ok",
        "tds": 250.0,
        "turbidity": 1.5,
        "wifi_rssi": -60,
        "uptime": 100,
        "firmware_version": "4.2.0"
    }
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["quality_score"] is not None
    assert data["screening_status"] == "GOOD"
    assert data["reading"]["sensor_status"] == "ok"
