"""
Phase 3 API Integration Tests: POST /api/readings with assessment + quality score.

Tests run against an isolated in-memory database built from the current ORM
metadata. MySQL connectivity is covered separately by the opt-in integration
suite.

PHASE 10 RETARGET (documented per plan section 9): the deterministic assessment
is now the two-parameter Parameter Rule Check (TDS + turbidity only), so
pH/temperature-driven expectations in tests B, C and F were rewritten; tests A,
H, I and K gained additive Phase 10 contract assertions. The isolated database is created from the current ORM metadata, so these tests
do not depend on a local or production MySQL schema.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models.water_reading import WaterReading
from app.models.prediction import Prediction, SafetyStatus, ScoreMethod
from app.security import require_admin_key

client = TestClient(app)
TestingSessionLocal = None


@pytest.fixture(scope="module", autouse=True)
def _isolated_database():
    global TestingSessionLocal
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    previous_db = app.dependency_overrides.get(get_db)
    def override_get_db():
        yield from _yield_session(TestingSessionLocal)

    app.dependency_overrides[get_db] = override_get_db

    previous_auth = app.dependency_overrides.get(require_admin_key)
    app.dependency_overrides[require_admin_key] = lambda: None
    yield
    if previous_db is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_db
    if previous_auth is None:
        app.dependency_overrides.pop(require_admin_key, None)
    else:
        app.dependency_overrides[require_admin_key] = previous_auth
    engine.dispose()


def _yield_session(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_isolated_database_is_available():
    assert TestingSessionLocal is not None
    with TestingSessionLocal() as db:
        assert db.execute(text("SELECT 1")).scalar_one() == 1


@pytest.fixture(autouse=True)
def _allow_config_updates_without_admin_key():
    """P2: PUT /api/config requires X-Admin-Key.

    This API suite exercises the config WRITE path (tests I/J),
    not authentication - auth is covered DB-free by test_admin_auth.py - so the
    admin-key dependency is overridden for these tests only and removed after.
    """
    yield


def test_post_reading_normal_water_safe():
    """Test A: Normal water values → SAFE status, high quality score."""
    payload = {
        "device_id": "PHASE3-SAFE-001",
        "ph": 7.1,
        "tds": 220.0,
        "turbidity": 1.5,
        "temperature": 26.5,
        "source": "SIMULATION"
    }
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()

    assert data["success"] is True
    assert data["safety_status"] == "SAFE"
    assert data["warning_message"] is None
    assert data["quality_score"] >= 80.0, f"Expected high score, got {data['quality_score']}"
    assert data["safety"]["status"] == "SAFE"
    assert data["safety"]["violated_parameters"] == []
    # Phase 10: primary assessment + discriminator are present for new records
    assert data["parameter_rule_check"]["status"] == "PASS"
    assert data["score_method"] == "TWO_PARAM_SCREENING"
    assert data["screening_status"] in ("GOOD", "MODERATE", "POOR", "UNAVAILABLE")
    # Phase 5: ML inference is active (EXPERIMENTAL / advisory)
    assert data["prediction"] in ("POTABLE", "NOT POTABLE")
    assert 0.0 <= data["confidence"] <= 1.0


def test_post_reading_abnormal_ph_warning():
    """Test B: Phase 10 RETARGET - pH slightly below the legacy minimum no longer
    changes the assessment (pH is not evaluated by the Parameter Rule Check);
    TDS 220 and turbidity 1.5 both PASS, so the record reads PASS / SAFE.
    """
    payload = {
        "device_id": "PHASE3-WARN-001",
        "ph": 6.1,           # below the legacy 6.5 min - NOT evaluated in Phase 10
        "tds": 220.0,
        "turbidity": 1.5,
        "temperature": 26.5,
        "source": "SIMULATION"
    }
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["parameter_rule_check"]["status"] == "PASS"
    assert data["safety_status"] == "SAFE"
    assert data["safety"]["violated_parameters"] == []
    assert "pH" not in data["safety"]["violated_parameters"]
    assert data["warning_message"] is None


def test_post_reading_severely_acidic_unsafe():
    """Test C: Phase 10 RETARGET - severely acidic pH no longer produces UNSAFE;
    the two-parameter score ignores pH entirely (deterministic 97.9 for
    TDS 220 / turbidity 1.5) and the rule check reports PASS.
    """
    payload = {
        "device_id": "PHASE3-UNSAFE-001",
        "ph": 3.5,           # well below legacy 6.0 - NOT evaluated in Phase 10
        "tds": 220.0,
        "turbidity": 1.5,
        "temperature": 26.5,
        "source": "SIMULATION"
    }
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["parameter_rule_check"]["status"] == "PASS"
    assert data["safety_status"] == "SAFE"
    assert data["safety"]["violated_parameters"] == []
    # Two-parameter score: S_tds(220)=98.6667, S_turb(1.5)=96.875 -> 97.8604 -> 97.9
    assert data["quality_score"] == 97.9, f"pH must not affect the screening score, got {data['quality_score']}"
    


def test_post_reading_high_tds_warning():
    """Test D: TDS moderately above threshold → WARNING."""
    payload = {
        "device_id": "PHASE3-TDS-001",
        "ph": 7.0,
        "tds": 650.0,        # above 500 but below 750 (500*1.5) → WARNING
        "turbidity": 1.5,
        "temperature": 26.5,
        "source": "SIMULATION"
    }
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["safety_status"] == "WARNING"
    assert "TDS" in data["safety"]["violated_parameters"]


def test_post_reading_high_turbidity_unsafe():
    """Test E: Turbidity severely above threshold → UNSAFE."""
    payload = {
        "device_id": "PHASE3-TURB-001",
        "ph": 7.0,
        "tds": 200.0,
        "turbidity": 45.0,   # well above 5.0*2.0 = 10.0 → UNSAFE
        "temperature": 26.5,
        "source": "SIMULATION"
    }
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["safety_status"] == "UNSAFE"
    assert "Turbidity" in data["safety"]["violated_parameters"]
    assert data["quality_score"] < 90.0, f"High turbidity water should have lower score, got {data['quality_score']}"


def test_post_reading_multiple_violations():
    """Test F: Phase 10 RETARGET - both evaluated parameters breach their FAIL
    thresholds, so both appear in violated_parameters; pH is not evaluated."""
    payload = {
        "device_id": "PHASE3-MULTI-001",
        "ph": 3.0,           # NOT evaluated in Phase 10
        "tds": 1000.0,       # FAIL (> 500*1.5 = 750)
        "turbidity": 80.0,   # FAIL (> 5.0*2.0 = 10.0)
        "temperature": 26.5,
        "source": "SIMULATION"
    }
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["parameter_rule_check"]["status"] == "FAIL"
    assert data["safety_status"] == "UNSAFE"
    violated = data["safety"]["violated_parameters"]
    assert "TDS" in violated
    assert "Turbidity" in violated
    assert "pH" not in violated
    assert data["quality_score"] < 60.0, f"Multiple violations should have lower score, got {data['quality_score']}"


def test_post_reading_quality_score_bounded():
    """Test G: Quality score is always in [0, 100] for extreme values."""
    payload = {
        "device_id": "PHASE3-BOUND-001",
        "ph": 0.1,
        "tds": 5000.0,
        "turbidity": 999.0,
        "temperature": 99.0,
        "source": "SIMULATION"
    }
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert 0.0 <= data["quality_score"] <= 100.0


def test_post_reading_persisted_in_mysql():
    """Test H: Reading and assessment are committed to MySQL."""
    payload = {
        "device_id": "PHASE3-PERSIST-001",
        "ph": 7.3,
        "tds": 180.0,
        "turbidity": 1.2,
        "temperature": 24.0,
        "source": "SIMULATION"
    }
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    reading_id = data["reading_id"]

    db: Session = TestingSessionLocal()
    try:
        db_reading = db.query(WaterReading).filter(WaterReading.id == reading_id).first()
        assert db_reading is not None
        assert abs(db_reading.ph - 7.3) < 0.01

        db_pred = db.query(Prediction).filter(Prediction.reading_id == reading_id).first()
        assert db_pred is not None
        assert db_pred.quality_score is not None
        assert db_pred.quality_score > 0.0
        assert db_pred.safety_status == SafetyStatus.SAFE
        # Phase 10: new records carry the discriminator (R-3)
        assert db_pred.score_method == ScoreMethod.TWO_PARAM_SCREENING
        # Phase 5: ML verdict persisted (EXPERIMENTAL / advisory)
        assert db_pred.prediction is not None
        assert db_pred.prediction.value in ("POTABLE", "NOT POTABLE")
        assert db_pred.confidence is not None
        assert 0.0 <= db_pred.confidence <= 1.0
    finally:
        db.close()


def test_config_endpoint_returns_thresholds():
    """Test I: GET /api/config returns valid threshold configuration."""
    res = client.get("/api/config")
    assert res.status_code == 200, res.text
    data = res.json()
    assert "ph_min" in data
    assert "ph_max" in data
    assert "tds_max" in data
    assert "turbidity_max" in data
    assert "temperature_min" in data
    assert "temperature_max" in data
    # Verify defaults are within sensible ranges
    assert data["ph_min"] < data["ph_max"]
    assert data["temperature_min"] < data["temperature_max"]
    # Phase 10: screening band fields are exposed with the invariant poor < good
    assert "status_good_min" in data
    assert "status_poor_max" in data
    assert 0.0 <= data["status_poor_max"] < data["status_good_min"] <= 100.0


def test_config_update_changes_thresholds():
    """Test J: PUT /api/config persists new threshold values."""
    update_payload = {
        "ph_min": 6.0,
        "ph_max": 9.0,
        "tds_max": 600.0,
        "turbidity_max": 6.0,
        "temperature_min": 8.0,
        "temperature_max": 38.0
    }
    res = client.put("/api/config", json=update_payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ph_min"] == 6.0
    assert data["ph_max"] == 9.0
    assert data["tds_max"] == 600.0

    # Reset to defaults
    reset_payload = {
        "ph_min": 6.5,
        "ph_max": 8.5,
        "tds_max": 500.0,
        "turbidity_max": 5.0,
        "temperature_min": 10.0,
        "temperature_max": 35.0
    }
    client.put("/api/config", json=reset_payload)


def test_latest_reading_includes_assessment():
    """Test K: GET /api/readings/latest returns quality_score and safety_status."""
    res = client.get("/api/readings/latest")
    assert res.status_code == 200, res.text
    data = res.json()
    assert "quality_score" in data
    assert "safety_status" in data
    assert data["quality_score"] is not None
    assert data["safety_status"] in ("SAFE", "WARNING", "UNSAFE")
    # Phase 10: new-row contract (primary field + discriminator present)
    assert data["score_method"] == "TWO_PARAM_SCREENING"
    assert data["parameter_rule_check"]["status"] in ("PASS", "WARNING", "FAIL", "UNAVAILABLE")
    assert data["screening_status"] in ("GOOD", "MODERATE", "POOR", "UNAVAILABLE")
