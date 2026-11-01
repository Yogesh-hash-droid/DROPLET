"""
Phase 10 contract tests (plan section 9, matrix rows T1-T27) - SQLite-executable set.

Every test gets a FRESH in-memory SQLite database (StaticPool), so band
mutations, seeded historical rows and injected failures never leak across tests
or into other test files.

Coverage map (SQLite-executable rows of the plan's matrix):
  T1      ESP8266 two-sensor ingestion returns the full new-record contract
  T2      exact screening score example (650 / 7.5 -> 71.5 GOOD)
  T3-T5   Parameter Rule Check PASS / WARNING / FAIL + terminology + disclaimer
  T6      aggregation order FAIL > WARNING > UNAVAILABLE > PASS; missing never PASS
  T7-T11  422 validation matrix (required missing/null/negative/bool/non-numeric,
          optional-field invalids, device/source) - nothing persisted on rejection
  T12     optional pH/temperature persisted as SQL NULL (verified directly)
  T13     legacy 6-key SIMULATION payload unchanged (values echoed exactly)
  T14     legacy ESP32 payload unchanged, ML runs when pH present
  T15     pH absent -> model NEVER invoked, PH_NOT_MEASURED, null verdict
  T16     pH present with a failing model -> explicit UNAVAILABLE reason
  T17     /api/predictions/latest: 404 without any stored verdict; NULL never
          renders as NOT POTABLE; stored verdicts served as-is
  T18     exact score examples (97.9 / 83.2 / 93.5 / 71.5)
  T19     band boundaries (70.0/69.9/40.0/39.9/None)
  T20     weights sum to 1.00 and clamping (0.0 and 100.0 extremes)
  T21     config compatibility + band fields + invalid band -> HTTP 400
  T22     DB failure -> HTTP 500 with explicit detail, no partial response
  T23     historical row served verbatim (P1 separation), never re-written
  T24     device API reports connectivity only (ONLINE/OFFLINE/404, no health)
  T25     regression files (test_phase3_services / test_simulator / test_health)
          run as-is in their own modules - nothing to duplicate here
  T26     band configurability end-to-end (PUT bands -> new classification)
  T27     read-path separation + primary "Parameter Rule Check" terminology
  T21b    non-finite configuration values rejected (400 service / 422 schema layer)
  +       non-finite ingestion inputs -> 422 with well-formed JSON bodies
          (Phase 10 non-finite input fix; +Infinity previously caused HTTP 500)

MySQL-only rows (T12's post-migration direct SELECT, T28, T29) live in
tests/test_readings_integration.py behind an explicit migration guard and are
BLOCKED until the separately approved migration runs.
"""
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.security import require_admin_key
from app.models.device import Device, DeviceSource, DeviceStatus
from app.models.prediction import Prediction, PotabilityResult, SafetyStatus
from app.models.water_reading import WaterReading
from app.services import config_service, quality_service, safety_service

# ---------------------------------------------------------------------------
# Fixtures: fresh in-memory database + dependency override per test.
# ---------------------------------------------------------------------------


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
    previous_admin = app.dependency_overrides.pop(require_admin_key, None)

    def override_get_db():
        session = db()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    # P2: PUT /api/config now requires X-Admin-Key. These contract tests cover
    # payload/validation contracts, not authentication (which is covered
    # DB-free by test_admin_auth.py), so the admin-key dependency is disabled
    # for this client only and restored on teardown.
    app.dependency_overrides[require_admin_key] = lambda: None
    yield TestClient(app)
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous
    if previous_admin is None:
        app.dependency_overrides.pop(require_admin_key, None)
    else:
        app.dependency_overrides[require_admin_key] = previous_admin


HARDWARE_PAYLOAD = {
    "device_id": "P10-HW-001",
    "tds": 300.0,
    "turbidity": 2.0,
    "source": "ESP8266",
}


def _post_lax(client, path, payload):
    """POST a payload that may contain Infinity/NaN JSON tokens.

    stdlib `json.dumps` emits these non-standard tokens (allow_nan=True) - the
    same wire format produced by Python `requests` and raw-socket hardware
    clients - while httpx's `json=` helper refuses them (allow_nan=False).
    The server parses them via stdlib json.loads and must reject them cleanly."""
    return client.post(
        path,
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )


def _put_lax(client, path, payload):
    """PUT counterpart of _post_lax (same wire-format reasoning)."""
    return client.put(
        path,
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )

LEGACY_PAYLOAD = {
    "device_id": "P10-LEGACY-001",
    "ph": 7.2,
    "tds": 410.0,
    "turbidity": 3.3,
    "temperature": 27.5,
    "source": "SIMULATION",
}

INGESTION_RESPONSE_KEYS = {
    "id", "reading_id", "device_id", "ph", "tds", "turbidity", "temperature",
    "source", "timestamp", "quality_score", "score_method", "screening_status",
    "screening_explanation", "parameter_rule_check", "safety_status",
    "warning_message", "safety", "reading", "prediction", "confidence",
    "ml_status", "ml_status_reason", "success",
}


def _config(session):
    return config_service.get_system_config(session)


def _seed_historical(db_factory, device_id="P10-LEGACY-SEED", days_ago=30):
    """Insert a pre-Phase-10 four-parameter record exactly as the legacy
    pipeline wrote it: score_method IS NULL, no screening fields."""
    ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago)
    session = db_factory()
    try:
        session.add(Device(
            device_id=device_id,
            device_name=f"Legacy seed ({device_id})",
            source=DeviceSource.SIMULATION,
            status=DeviceStatus.ONLINE,
            last_seen=ts,
            created_at=ts,
        ))
        session.flush()
        reading = WaterReading(
            device_id=device_id,
            ph=7.0,
            tds=300.0,
            turbidity=2.0,
            temperature=25.0,
            source=DeviceSource.SIMULATION,
            timestamp=ts,
        )
        session.add(reading)
        session.flush()
        session.add(Prediction(
            reading_id=reading.id,
            prediction=PotabilityResult.POTABLE,
            confidence=0.612345,
            quality_score=84.6,
            score_method=None,  # historical discriminator (R-3)
            safety_status=SafetyStatus.WARNING,
            warning_message="legacy four-parameter assessment",
            timestamp=ts,
        ))
        session.commit()
        return reading.id
    finally:
        session.close()


# ---------------------------------------------------------------------------
# T1 - ESP8266 two-sensor ingestion contract
# ---------------------------------------------------------------------------

def test_t1_esp8266_ingestion_contract(client):
    """T1: tds + turbidity only -> 201 with the complete new-record contract,
    NULL optional sensors, the two-parameter assessment and ML skipped."""
    res = client.post("/api/readings", json=HARDWARE_PAYLOAD)
    assert res.status_code == 201, res.text
    data = res.json()

    # Exact top-level contract (additive Phase 10 fields included)
    assert set(data.keys()) == INGESTION_RESPONSE_KEYS

    # Echoed reading values
    assert data["device_id"] == "P10-HW-001"
    assert data["source"] == "ESP8266"
    assert data["tds"] == 300.0
    assert data["turbidity"] == 2.0
    assert data["ph"] is None
    assert data["temperature"] is None
    assert data["reading"]["ph"] is None
    assert data["reading"]["temperature"] is None

    # Screening: S_tds(300)=93.3333, S_turb(2.0)=93.75 -> 93.5208 -> 93.5 GOOD
    assert data["score_method"] == "TWO_PARAM_SCREENING"
    assert data["quality_score"] == 93.5
    assert data["screening_status"] == "GOOD"
    assert data["screening_explanation"]

    # Primary assessment: PASS with both parameters evaluated
    prc = data["parameter_rule_check"]
    assert prc["label"] == "Parameter Rule Check"
    assert prc["status"] == "PASS"
    assert set(prc["parameters"].keys()) == {"tds", "turbidity"}
    assert prc["parameters"]["tds"]["unit"] == "ppm"
    assert prc["parameters"]["turbidity"]["unit"] == "NTU"
    assert prc["unavailable_parameters"] == []
    assert prc["scope"] == "TDS and turbidity only"
    assert "Laboratory testing is required" in prc["disclaimer"]

    # Deprecated storage mirrors only
    assert data["safety_status"] == "SAFE"
    assert data["safety"]["status"] == "SAFE"
    assert data["safety"]["violated_parameters"] == []

    # ML skipped: explicit reason, never a fabricated verdict
    assert data["ml_status"] == "UNAVAILABLE"
    assert data["ml_status_reason"] == "PH_NOT_MEASURED"
    assert data["prediction"] is None
    assert data["confidence"] is None
    assert data["success"] is True


# ---------------------------------------------------------------------------
# T2 - exact screening score example
# ---------------------------------------------------------------------------

def test_t2_screening_score_example(client, db):
    """T2: 650 ppm / 7.5 NTU -> S_tds=72.0, S_turb=70.8333 -> 71.475 -> 71.5 GOOD."""
    session = db()
    try:
        result = quality_service.calculate_screening_score(
            tds=650.0, turbidity=7.5, config=_config(session)
        )
    finally:
        session.close()
    assert result.overall_score == 71.5
    assert result.sub_scores == {"tds": 72.0, "turbidity": 70.8333}
    assert result.weights == {"tds": 0.55, "turbidity": 0.45}
    assert result.screening_status == "GOOD"
    assert result.unavailable_reason is None


# ---------------------------------------------------------------------------
# T3-T5 - Parameter Rule Check outcomes + terminology
# ---------------------------------------------------------------------------

def test_t3_rule_check_pass(client, db):
    """T3: both parameters within limits -> PASS, SAFE mirror, no warning."""
    session = db()
    try:
        result = safety_service.evaluate_parameter_rule_check(
            tds=220.0, turbidity=1.5, config=_config(session)
        )
    finally:
        session.close()
    assert result.status == "PASS"
    assert result.storage_status == SafetyStatus.SAFE
    assert result.warning_message is None
    assert result.unavailable_parameters == []
    assert [p.status for p in result.parameters] == ["PASS", "PASS"]


def test_t4_rule_check_warning(client, db):
    """T4: TDS 650 (<= 500*1.5) -> WARNING with the exact contract detail."""
    session = db()
    try:
        result = safety_service.evaluate_parameter_rule_check(
            tds=650.0, turbidity=1.5, config=_config(session)
        )
    finally:
        session.close()
    expected_detail = (
        "TDS (650.0 ppm) is moderately above preferred threshold (500.0 ppm)"
    )
    assert result.status == "WARNING"
    assert result.storage_status == SafetyStatus.WARNING
    assert result.warning_message == expected_detail
    assert result.parameters[0].detail == expected_detail
    assert result.parameters[1].status == "PASS"


def test_t5_rule_check_fail_and_terminology(client):
    """T5: turbidity 45 (> 5*2.0) -> FAIL/UNSAFE mirror; the API block uses the
    primary 'Parameter Rule Check' vocabulary and the lab disclaimer."""
    session_payload = {
        "device_id": "P10-T5-001",
        "tds": 200.0,
        "turbidity": 45.0,
        "source": "ESP8266",
    }
    res = client.post("/api/readings", json=session_payload)
    assert res.status_code == 201, res.text
    data = res.json()
    prc = data["parameter_rule_check"]
    assert prc["status"] == "FAIL"
    assert prc["label"] == "Parameter Rule Check"
    assert prc["parameters"]["turbidity"]["detail"] == (
        "Turbidity (45.0 NTU) severely exceeds clarity threshold (5.0 NTU)"
    )
    assert "does NOT certify" in prc["disclaimer"]
    assert "Laboratory testing is required" in prc["disclaimer"]
    assert data["safety_status"] == "UNSAFE"
    assert data["safety"]["violated_parameters"] == ["Turbidity"]


# ---------------------------------------------------------------------------
# T6 - aggregation order and "missing never PASS"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tds,turbidity,expected",
    [
        (1000.0, 1.0, "FAIL"),          # FAIL beats PASS
        (650.0, 1.5, "WARNING"),        # WARNING beats PASS
        (1000.0, None, "FAIL"),         # FAIL beats UNAVAILABLE
        (650.0, None, "WARNING"),       # WARNING beats UNAVAILABLE
        (None, 1.0, "UNAVAILABLE"),     # missing beats PASS
        (None, None, "UNAVAILABLE"),    # incomplete check can never read PASS
        (220.0, 1.5, "PASS"),           # only both measured + in range
    ],
    ids=[
        "T6-fail-beats-pass", "T6-warning-beats-pass", "T6-fail-beats-unavailable",
        "T6-warning-beats-unavailable", "T6-missing-beats-pass",
        "T6-all-missing-never-pass", "T6-both-measured-pass",
    ],
)
def test_t6_rule_check_ordering(db, tds, turbidity, expected):
    """T6: overall order FAIL > WARNING > UNAVAILABLE > PASS; a missing
    parameter is never PASS and never masked by a passing neighbour."""
    session = db()
    try:
        result = safety_service.evaluate_parameter_rule_check(
            tds=tds, turbidity=turbidity, config=_config(session)
        )
    finally:
        session.close()
    assert result.status == expected
    if expected == "UNAVAILABLE":
        assert result.unavailable_parameters


# ---------------------------------------------------------------------------
# T7-T11 - 422 validation matrix; nothing persisted on rejection
# ---------------------------------------------------------------------------

INVALID_PAYLOADS = [
    # (id, payload)
    ("T7-missing-tds", {"device_id": "V1", "turbidity": 2.0, "source": "ESP8266"}),
    ("T7-null-tds", {"device_id": "V2", "tds": None, "turbidity": 2.0, "source": "ESP8266"}),
    ("T8-negative-tds", {"device_id": "V3", "tds": -1.0, "turbidity": 2.0, "source": "ESP8266"}),
    ("T9-boolean-tds", {"device_id": "V4", "tds": True, "turbidity": 2.0, "source": "ESP8266"}),
    # T10: genuinely non-numeric strings are rejected. (Numeric strings such as
    # "300" are coerced by Pydantic v2's lax float parsing - behaviour inherited
    # unchanged from the pre-Phase-10 `float` fields - see the dedicated test.)
    ("T10-non-numeric-tds", {"device_id": "V5", "tds": "abc", "turbidity": 2.0, "source": "ESP8266"}),
    ("T7-missing-turbidity", {"device_id": "V6", "tds": 300.0, "source": "ESP8266"}),
    ("T7-null-turbidity", {"device_id": "V7", "tds": 300.0, "turbidity": None, "source": "ESP8266"}),
    ("T8-negative-turbidity", {"device_id": "V8", "tds": 300.0, "turbidity": -0.5, "source": "ESP8266"}),
    ("T9-boolean-turbidity", {"device_id": "V9", "tds": 300.0, "turbidity": False, "source": "ESP8266"}),
    ("T10-non-numeric-turbidity", {"device_id": "V10", "tds": 300.0, "turbidity": "ntu", "source": "ESP8266"}),
    # Optional fields: present-but-invalid is rejected; absent is fine (T1).
    ("T11-negative-ph", {"device_id": "V11", "ph": -1.0, "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-out-of-range-ph", {"device_id": "V12", "ph": 15.0, "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-boolean-ph", {"device_id": "V13", "ph": True, "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-non-numeric-ph", {"device_id": "V14", "ph": "acidic", "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-negative-temperature", {"device_id": "V15", "temperature": -20.0, "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-out-of-range-temperature", {"device_id": "V16", "temperature": 150.0, "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-boolean-temperature", {"device_id": "V17", "temperature": True, "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-non-numeric-temperature", {"device_id": "V18", "temperature": "warm", "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-missing-device-id", {"tds": 300.0, "turbidity": 2.0, "source": "ESP8266"}),
    ("T11-empty-device-id", {"device_id": "", "tds": 300.0, "turbidity": 2.0, "source": "ESP8266"}),
    ("T11-unknown-source", {"device_id": "V19", "tds": 300.0, "turbidity": 2.0, "source": "DRONE"}),
    # Non-finite measurements (Phase 10 non-finite input fix): +/-Infinity and
    # NaN must never reach scoring or storage (+Infinity previously caused a 500).
    ("T10-pos-infinity-tds", {"device_id": "V20", "tds": float("inf"), "turbidity": 2.0, "source": "ESP8266"}),
    ("T10-neg-infinity-tds", {"device_id": "V21", "tds": float("-inf"), "turbidity": 2.0, "source": "ESP8266"}),
    ("T10-nan-tds", {"device_id": "V22", "tds": float("nan"), "turbidity": 2.0, "source": "ESP8266"}),
    ("T10-pos-infinity-turbidity", {"device_id": "V23", "tds": 300.0, "turbidity": float("inf"), "source": "ESP8266"}),
    ("T10-neg-infinity-turbidity", {"device_id": "V24", "tds": 300.0, "turbidity": float("-inf"), "source": "ESP8266"}),
    ("T10-nan-turbidity", {"device_id": "V25", "tds": 300.0, "turbidity": float("nan"), "source": "ESP8266"}),
    ("T11-pos-infinity-ph", {"device_id": "V26", "ph": float("inf"), "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-nan-ph", {"device_id": "V27", "ph": float("nan"), "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-pos-infinity-temperature", {"device_id": "V28", "temperature": float("inf"), "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-neg-infinity-temperature", {"device_id": "V29", "temperature": float("-inf"), "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
    ("T11-nan-temperature", {"device_id": "V30", "temperature": float("nan"), "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}),
]


@pytest.mark.parametrize("payload", [p for _, p in INVALID_PAYLOADS], ids=[i for i, _ in INVALID_PAYLOADS])
def test_t7_t11_validation_matrix(client, db, payload):
    """T7-T11: every invalid required/optional variant -> 422, and a rejected
    request persists NOTHING (no reading, no assessment). _post_lax is used so
    non-finite payloads reach the server as raw Infinity/NaN JSON tokens."""
    res = _post_lax(client, "/api/readings", payload)
    assert res.status_code == 422, res.text

    session = db()
    try:
        assert session.query(WaterReading).count() == 0
        assert session.query(Prediction).count() == 0
        assert session.query(Device).count() == 0
    finally:
        session.close()


@pytest.mark.parametrize("field,value", [("tds", 0.0), ("turbidity", 0.0)])
def test_boundary_zero_required_values_accepted(client, field, value):
    """ge=0 is inclusive: zero TDS/turbidity is a valid (if poor) measurement."""
    payload = {"device_id": f"P10-ZERO-{field}", "tds": 300.0, "turbidity": 2.0, "source": "ESP8266"}
    payload[field] = value
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text


@pytest.mark.parametrize(
    "field,value,expected",
    [("tds", "300", 300.0), ("turbidity", "2.0", 2.0), ("ph", "7.0", 7.0), ("temperature", "25", 25.0)],
)
def test_numeric_strings_remain_coerced_legacy_behaviour(client, field, value, expected):
    """Numeric strings are coerced to floats by Pydantic v2's lax parsing - the
    exact behaviour of the pre-Phase-10 `float` fields, left unchanged (the 422
    matrix targets missing/null/negative/boolean/non-numeric values)."""
    payload = {"device_id": f"P10-COERCE-{field}", "tds": 300.0, "turbidity": 2.0, "source": "SIMULATION"}
    payload[field] = value
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    assert res.json()[field] == expected


# ---------------------------------------------------------------------------
# Non-finite input fix: 422 responses must stay valid JSON (regression for the
# default handler crash that turned rejected -Infinity/NaN inputs into 500s).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload,expected_field,expected_echo",
    [
        ({"device_id": "NF-JSON-1", "tds": float("-inf"), "turbidity": 2.0, "source": "ESP8266"}, "tds", "-inf"),
        ({"device_id": "NF-JSON-2", "tds": float("inf"), "turbidity": 2.0, "source": "ESP8266"}, "tds", "inf"),
        ({"device_id": "NF-JSON-3", "tds": 300.0, "turbidity": float("nan"), "source": "ESP8266"}, "turbidity", "nan"),
        ({"device_id": "NF-JSON-4", "ph": float("inf"), "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}, "ph", "inf"),
        ({"device_id": "NF-JSON-5", "temperature": float("-inf"), "tds": 300.0, "turbidity": 2.0, "source": "ESP32"}, "temperature", "-inf"),
    ],
    ids=["neg-inf-tds", "pos-inf-tds", "nan-turbidity", "pos-inf-ph", "neg-inf-temperature"],
)
def test_non_finite_rejection_returns_valid_json_422(client, db, payload, expected_field, expected_echo):
    """A rejected non-finite input yields a well-formed 422 whose body parses;
    the offending input is echoed as a STRING (never a bare Infinity/NaN float
    token that starlette's JSONResponse cannot serialize)."""
    res = _post_lax(client, "/api/readings", payload)
    assert res.status_code == 422, res.text  # res.json() parsing proves valid JSON
    detail = res.json()["detail"]
    assert isinstance(detail, list) and detail
    assert detail[0]["loc"] == ["body", expected_field]
    assert detail[0]["type"] == "finite_number"
    assert detail[0]["input"] == expected_echo  # sanitized to a JSON-safe string

    session = db()
    try:
        assert session.query(WaterReading).count() == 0
        assert session.query(Prediction).count() == 0
    finally:
        session.close()


# ---------------------------------------------------------------------------
# T12 - optional values persisted as SQL NULL
# ---------------------------------------------------------------------------

def test_t12_optional_values_stored_as_null(client, db):
    """T12: POST the two-sensor payload, then SELECT the row directly - ph and
    temperature are SQL NULL in the database, not defaulted or fabricated."""
    res = client.post("/api/readings", json=HARDWARE_PAYLOAD)
    assert res.status_code == 201, res.text
    reading_id = res.json()["reading_id"]

    session = db()
    try:
        row = session.query(WaterReading).filter(WaterReading.id == reading_id).first()
        assert row is not None
        assert row.ph is None
        assert row.temperature is None
        # discriminator persisted (R-3)
        assert row.assessment.score_method.value == "TWO_PARAM_SCREENING"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# T13-T14 - legacy payload compatibility
# ---------------------------------------------------------------------------

def test_t13_legacy_simulation_payload_unchanged(client):
    """T13: the 6-key SIMULATION payload keeps working; values are echoed
    exactly as sent and the two-parameter assessment is computed from them."""
    res = client.post("/api/readings", json=LEGACY_PAYLOAD)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["ph"] == 7.2
    assert data["tds"] == 410.0
    assert data["turbidity"] == 3.3
    assert data["temperature"] == 27.5
    assert data["source"] == "SIMULATION"
    assert data["score_method"] == "TWO_PARAM_SCREENING"
    assert data["parameter_rule_check"]["status"] == "PASS"  # 410 <= 500, 3.3 <= 5.0
    assert data["safety_status"] == "SAFE"


def test_t14_legacy_esp32_payload_ml_runs(client, monkeypatch):
    """T14: legacy ESP32 payloads still ingest; with pH present the ML step is
    attempted and its verdict is returned as-is."""
    from app.services import reading_service

    calls = []

    def _stub(**kwargs):
        calls.append(kwargs)

        class _Result:
            prediction = "POTABLE"
            confidence = 0.87

        return _Result()

    monkeypatch.setattr(reading_service.ml_service, "predict_reading", _stub)

    payload = dict(LEGACY_PAYLOAD, device_id="P10-LEGACY-ESP32", source="ESP32")
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert calls == [{"ph": 7.2, "tds": 410.0, "turbidity": 3.3}]
    assert data["ml_status"] == "AVAILABLE"
    assert data["ml_status_reason"] is None
    assert data["prediction"] == "POTABLE"
    assert data["confidence"] == 0.87
    # The deterministic outputs are untouched by the ML verdict
    assert data["parameter_rule_check"]["status"] == "PASS"
    assert data["safety_status"] == "SAFE"


# ---------------------------------------------------------------------------
# T15-T16 - conditional ML invocation and failure reasons
# ---------------------------------------------------------------------------

def test_t15_ph_absent_model_never_invoked(client, monkeypatch):
    """T15: without pH the model is NEVER called - no default pH, no verdict,
    explicit PH_NOT_MEASURED reason (NULL never means NOT POTABLE)."""
    from app.services import reading_service

    calls = []

    def _forbidden(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("model must not be invoked without pH")

    monkeypatch.setattr(reading_service.ml_service, "predict_reading", _forbidden)

    res = client.post("/api/readings", json=HARDWARE_PAYLOAD)
    assert res.status_code == 201, res.text
    assert calls == []  # the model was never asked for a prediction
    data = res.json()
    assert data["ml_status"] == "UNAVAILABLE"
    assert data["ml_status_reason"] == "PH_NOT_MEASURED"
    assert data["prediction"] is None
    assert data["confidence"] is None


def test_t16_ph_present_model_failure_is_explicit(client, monkeypatch):
    """T16: pH present + exploding model -> ingestion still succeeds (201) with
    a NULL verdict and an explicit UNAVAILABLE reason (never PH_NOT_MEASURED)."""
    from app.services import reading_service

    def _boom(**kwargs):
        raise RuntimeError("simulated model outage")

    monkeypatch.setattr(reading_service.ml_service, "predict_reading", _boom)

    payload = dict(LEGACY_PAYLOAD, device_id="P10-T16-001")
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["ml_status"] == "UNAVAILABLE"
    assert data["ml_status_reason"] in {"MODEL_UNAVAILABLE", "INFERENCE_FAILED"}
    assert data["ml_status_reason"] != "PH_NOT_MEASURED"
    assert data["prediction"] is None
    assert data["confidence"] is None
    # The deterministic assessment is unaffected by the ML failure
    assert data["parameter_rule_check"]["status"] == "PASS"
    assert data["screening_status"] in {"GOOD", "MODERATE", "POOR"}


# ---------------------------------------------------------------------------
# T17 - /api/predictions/latest null vs verdict
# ---------------------------------------------------------------------------

def test_t17_predictions_latest_null_vs_verdict(client, monkeypatch):
    """T17: no stored verdict -> 404 (never a fabricated NOT POTABLE); a stored
    verdict is served as-is even when later readings have NULL predictions."""
    from app.services import reading_service

    # 1) pH-absent reading only: nothing stored -> 404, never "NOT POTABLE"
    res = client.post("/api/readings", json={"device_id": "P10-T17-A", "tds": 300.0, "turbidity": 2.0, "source": "ESP8266"})
    assert res.status_code == 201, res.text
    latest = client.get("/api/predictions/latest")
    assert latest.status_code == 404
    assert "NOT POTABLE" not in latest.text

    # 2) pH-present reading with a stubbed verdict -> 200 with that verdict
    def _stub(**kwargs):
        class _Result:
            prediction = "POTABLE"
            confidence = 0.42

        return _Result()

    monkeypatch.setattr(reading_service.ml_service, "predict_reading", _stub)
    res = client.post("/api/readings", json=dict(LEGACY_PAYLOAD, device_id="P10-T17-B"))
    assert res.status_code == 201, res.text
    verdict_reading_id = res.json()["reading_id"]

    # 3) a later pH-absent reading must NOT displace or null the stored verdict
    res = client.post("/api/readings", json={"device_id": "P10-T17-C", "tds": 150.0, "turbidity": 1.0, "source": "ESP8266"})
    assert res.status_code == 201, res.text

    latest = client.get("/api/predictions/latest")
    assert latest.status_code == 200, latest.text
    data = latest.json()
    assert data["prediction"] == "POTABLE"
    assert data["confidence"] == 0.42
    assert data["reading_id"] == verdict_reading_id
    assert data["ml_status"] == "EXPERIMENTAL"
    assert "not a guarantee" in data["disclaimer"].lower()
    assert data["safety_status"] in {"SAFE", "WARNING", "UNSAFE"}
    assert data["temperature_used"] is False


# ---------------------------------------------------------------------------
# T18-T20 - exact scores, band boundaries, weights and clamping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tds,turbidity,expected_score,expected_band",
    [
        (220.0, 1.5, 97.9, "GOOD"),   # S_tds=98.6667, S_turb=96.875
        (650.0, 1.5, 83.2, "GOOD"),   # S_tds=72.0,    S_turb=96.875
        (300.0, 2.0, 93.5, "GOOD"),   # S_tds=93.3333, S_turb=93.75
        (650.0, 7.5, 71.5, "GOOD"),   # S_tds=72.0,    S_turb=70.8333
    ],
    ids=["T18-clean", "T18-tds-warning", "T18-hardware", "T18-both-moderate"],
)
def test_t18_exact_score_examples(db, tds, turbidity, expected_score, expected_band):
    session = db()
    try:
        result = quality_service.calculate_screening_score(
            tds=tds, turbidity=turbidity, config=_config(session)
        )
    finally:
        session.close()
    assert result.overall_score == expected_score
    assert result.screening_status == expected_band


@pytest.mark.parametrize(
    "score,expected",
    [
        (70.0, "GOOD"),
        (69.9, "MODERATE"),
        (40.0, "MODERATE"),
        (39.9, "POOR"),
        (0.0, "POOR"),
        (None, "UNAVAILABLE"),
    ],
    ids=["T19-good-min", "T19-below-good", "T19-poor-max", "T19-below-poor", "T19-zero", "T19-none"],
)
def test_t19_band_boundaries(db, score, expected):
    """T19: B1 database-backed boundaries - GOOD >= 70.0, MODERATE >= 40.0,
    POOR below, UNAVAILABLE for a missing score."""
    session = db()
    try:
        config = _config(session)
        assert config.status_good_min == 70.0
        assert config.status_poor_max == 40.0
        assert quality_service.classify_screening_status(score, config) == expected
    finally:
        session.close()


def test_t20_weights_and_clamping(db):
    """T20: weights sum to 1.00 and the score is clamped to [0, 100]."""
    session = db()
    try:
        config = _config(session)
        worst = quality_service.calculate_screening_score(tds=2000.0, turbidity=50.0, config=config)
        best = quality_service.calculate_screening_score(tds=0.0, turbidity=0.0, config=config)
        edge = quality_service.calculate_screening_score(tds=500.0, turbidity=5.0, config=config)
    finally:
        session.close()
    assert round(sum(worst.weights.values()), 2) == 1.00
    assert worst.weights == {"tds": 0.55, "turbidity": 0.45}
    assert worst.overall_score == 0.0
    assert worst.screening_status == "POOR"
    assert best.overall_score == 100.0
    assert best.screening_status == "GOOD"
    # S_tds(500)=80, S_turb(5.0)=75 -> 44.0 + 33.75 = 77.75 -> 77.8
    assert edge.overall_score == 77.8
    assert edge.screening_status == "GOOD"


# ---------------------------------------------------------------------------
# T21 - config compatibility, band fields and 400 validation
# ---------------------------------------------------------------------------

def test_t21_config_contract_and_band_validation(client):
    # GET: legacy keys intact + band fields with defaults
    res = client.get("/api/config")
    assert res.status_code == 200, res.text
    data = res.json()
    for key in ("ph_min", "ph_max", "tds_max", "turbidity_max", "temperature_min", "temperature_max"):
        assert key in data
    assert data["status_good_min"] == 70.0
    assert data["status_poor_max"] == 40.0

    # Partial legacy update leaves the rest (incl. bands) untouched
    res = client.put("/api/config", json={"ph_min": 6.0})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ph_min"] == 6.0
    assert data["tds_max"] == 500.0
    assert data["status_good_min"] == 70.0
    assert data["status_poor_max"] == 40.0

    # Valid band update
    res = client.put("/api/config", json={"status_good_min": 80.0, "status_poor_max": 50.0})
    assert res.status_code == 200, res.text
    assert res.json()["status_good_min"] == 80.0
    assert res.json()["status_poor_max"] == 50.0

    # Invalid band configurations -> HTTP 400 (service-level, not 422)
    for bad in (
        {"status_good_min": 50.0, "status_poor_max": 60.0},  # ordering violated
        {"status_good_min": 80.0, "status_poor_max": 80.0},  # not strictly less
        {"status_good_min": 120.0},                          # out of [0, 100]
        {"status_poor_max": -5.0},                           # out of [0, 100]
    ):
        res = client.put("/api/config", json=bad)
        assert res.status_code == 400, f"{bad} -> {res.status_code}: {res.text}"

    # Restore defaults (fresh DB per test, but keep the test self-contained)
    res = client.put("/api/config", json={"status_good_min": 70.0, "status_poor_max": 40.0, "ph_min": 6.5})
    assert res.status_code == 200, res.text


def test_t21b_config_rejects_non_finite_values(client):
    """Non-finite configuration values are rejected and never persisted.

    Layered design preserved: fields without schema constraints (both screening
    bands, temperature_min/max) reach the service and get HTTP 400; fields that
    already carry schema ge/le constraints reject values failing those bounds
    with the schema-level 422 (same layer as negative values today). Every
    response is well-formed JSON (raw Infinity/NaN tokens via _put_lax)."""
    inf, ninf, nan = float("inf"), float("-inf"), float("nan")

    # Screening bands (the configurable thresholds): every non-finite variant -> 400
    for bad in (inf, ninf, nan):
        for field in ("status_good_min", "status_poor_max"):
            res = _put_lax(client, "/api/config", {field: bad})
            assert res.status_code == 400, f"{field}={bad!r} -> {res.status_code}: {res.text}"
            assert "finite" in res.json()["detail"]

    # Legacy thresholds used by the rule check / scoring: +Infinity previously
    # PASSED ge=0.0 and was stored -> now 400; temperature fields were entirely
    # unconstrained (NaN/Infinity were stored) -> now 400.
    for field, bad in (
        ("tds_max", inf),
        ("turbidity_max", inf),
        ("temperature_min", nan),
        ("temperature_max", -inf),
    ):
        res = _put_lax(client, "/api/config", {field: bad})
        assert res.status_code == 400, f"{field}={bad!r} -> {res.status_code}: {res.text}"
        assert "finite" in res.json()["detail"]

    # Schema-constrained legacy fields keep their pre-existing layer: ph_min=inf
    # fails le=14.0 at the schema -> 422, and the 422 body stays valid JSON.
    res = _put_lax(client, "/api/config", {"ph_min": inf})
    assert res.status_code == 422, res.text
    assert isinstance(res.json()["detail"], list)
    res = _put_lax(client, "/api/config", {"tds_max": nan})  # NaN fails schema ge=0.0 -> 422
    assert res.status_code == 422, res.text

    # Nothing above changed the stored configuration
    res = client.get("/api/config")
    assert res.status_code == 200
    data = res.json()
    assert data["status_good_min"] == 70.0
    assert data["status_poor_max"] == 40.0
    assert data["tds_max"] == 500.0
    assert data["turbidity_max"] == 5.0
    assert data["temperature_min"] == 10.0
    assert data["temperature_max"] == 35.0
    assert data["ph_min"] == 6.5


# ---------------------------------------------------------------------------
# T22 - database failure -> explicit 500, no partial response
# ---------------------------------------------------------------------------

def test_t22_db_failure_returns_500_without_partial_response(client, db, monkeypatch):
    """T22: a failing commit surfaces as HTTP 500 with the explicit detail and
    nothing at all is persisted (reading + assessment are atomic)."""

    def _boom(self):
        raise RuntimeError("simulated database outage")

    monkeypatch.setattr(Session, "commit", _boom)

    res = client.post("/api/readings", json=HARDWARE_PAYLOAD)
    assert res.status_code == 500
    detail = res.json()["detail"]
    assert "Failed to persist reading and evaluation" in detail
    assert "simulated database outage" in detail

    monkeypatch.undo()  # reads need no commit; restore so cleanup can run
    session = db()
    try:
        assert session.query(WaterReading).count() == 0
        assert session.query(Prediction).count() == 0
    finally:
        session.close()


# ---------------------------------------------------------------------------
# T23 - historical record served verbatim (P1 separation)
# ---------------------------------------------------------------------------

def test_t23_historical_row_verbatim(client, db):
    """T23: a pre-Phase-10 row keeps its stored meaning - explicit nulls for
    Phase 10 fields, no re-banding, no re-derivation, no writes on read."""
    reading_id = _seed_historical(db)

    res = client.get("/api/readings/latest")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["id"] == reading_id
    assert data["ph"] == 7.0
    assert data["tds"] == 300.0
    assert data["quality_score"] == 84.6        # stored four-parameter score, verbatim
    assert data["score_method"] is None         # historical discriminator
    assert data["screening_status"] is None     # never re-banded (84.6 is NOT mapped to GOOD)
    assert data["parameter_rule_check"] is None
    assert data["prediction"] == "POTABLE"      # stored ML verdict preserved
    assert data["confidence"] == 0.612345
    assert data["safety_status"] == "WARNING"   # stored legacy assessment, verbatim
    assert data["warning_message"] == "legacy four-parameter assessment"
    assert data["ml_status"] is None            # no new ML claim for historical rows
    assert data["ml_status_reason"] is None

    res = client.get("/api/readings/history")
    assert res.status_code == 200, res.text
    history = res.json()
    assert len(history) == 1
    assert history[0]["quality_score"] == 84.6

    # Reading never writes: the stored row is byte-for-byte untouched
    session = db()
    try:
        row = session.query(WaterReading).filter(WaterReading.id == reading_id).first()
        assessment = row.assessment
        assert assessment.quality_score == 84.6
        assert assessment.score_method is None
        assert assessment.prediction == PotabilityResult.POTABLE
        assert assessment.safety_status == SafetyStatus.WARNING
    finally:
        session.close()


# ---------------------------------------------------------------------------
# T24 - device API: connectivity only
# ---------------------------------------------------------------------------

def test_t24_device_api_connectivity_only(client, db):
    """T24: the device endpoint reports connectivity (ONLINE/OFFLINE) derived
    from last_seen - and nothing about sensor health."""
    res = client.post("/api/readings", json=HARDWARE_PAYLOAD)
    assert res.status_code == 201, res.text

    res = client.get("/api/devices/P10-HW-001")
    assert res.status_code == 200, res.text
    data = res.json()
    # Exact key set: no sensor-health / WORKING claims exist to extend this
    assert set(data.keys()) == {"id", "device_id", "device_name", "source", "status", "last_seen", "created_at"}
    assert data["device_id"] == "P10-HW-001"
    assert data["source"] == "ESP8266"
    assert data["status"] == "ONLINE"

    # Unknown device -> 404 (no fabricated device records)
    res = client.get("/api/devices/DOES-NOT-EXIST")
    assert res.status_code == 404

    # Stale last_seen -> OFFLINE (computed at read time)
    session = db()
    try:
        device = session.query(Device).filter(Device.device_id == "P10-HW-001").first()
        device.last_seen = datetime(2000, 1, 1)
        session.commit()
    finally:
        session.close()
    res = client.get("/api/devices/P10-HW-001")
    assert res.status_code == 200
    assert res.json()["status"] == "OFFLINE"


# ---------------------------------------------------------------------------
# T26 - band configurability end-to-end
# ---------------------------------------------------------------------------

def test_t26_band_configurability_end_to_end(client):
    """T26: changing the configured bands changes the classification of NEW
    readings while leaving the rule check untouched (bands are screen-only)."""
    payload = {"device_id": "P10-T26-001", "tds": 650.0, "turbidity": 7.5, "source": "ESP8266"}

    # Default bands: 71.5 >= 70.0 -> GOOD (rule check: both parameters WARNING)
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    assert res.json()["quality_score"] == 71.5
    assert res.json()["screening_status"] == "GOOD"
    assert res.json()["parameter_rule_check"]["status"] == "WARNING"

    # Raise the GOOD threshold above the score -> MODERATE
    res = client.put("/api/config", json={"status_good_min": 80.0, "status_poor_max": 50.0})
    assert res.status_code == 200, res.text
    res = client.post("/api/readings", json=dict(payload, device_id="P10-T26-002"))
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["quality_score"] == 71.5       # the score itself is band-independent
    assert data["screening_status"] == "MODERATE"
    # Bands never affect the rule check (650 > 500 stays WARNING)
    assert data["parameter_rule_check"]["status"] == "WARNING"
    assert data["safety_status"] == "WARNING"

    # Restore defaults -> GOOD again
    res = client.put("/api/config", json={"status_good_min": 70.0, "status_poor_max": 40.0})
    assert res.status_code == 200, res.text
    res = client.post("/api/readings", json=dict(payload, device_id="P10-T26-003"))
    assert res.status_code == 201, res.text
    assert res.json()["screening_status"] == "GOOD"


# ---------------------------------------------------------------------------
# T27 - read-path separation + primary terminology in a mixed history
# ---------------------------------------------------------------------------

def test_t27_mixed_history_separation_and_terminology(client, db):
    """T27: historical and new rows coexist with strict P1 separation; the new
    row presents the Parameter Rule Check as the primary assessment."""
    historical_id = _seed_historical(db)

    res = client.post("/api/readings", json=HARDWARE_PAYLOAD)
    assert res.status_code == 201, res.text
    new_id = res.json()["reading_id"]

    res = client.get("/api/readings/history")
    assert res.status_code == 200, res.text
    rows = res.json()
    assert [row["id"] for row in rows] == [new_id, historical_id]  # newest first

    new_row, old_row = rows

    # New row: primary vocabulary; read-path separation fields (plan section 3.3)
    assert new_row["score_method"] == "TWO_PARAM_SCREENING"
    assert new_row["screening_status"] == "GOOD"
    prc = new_row["parameter_rule_check"]
    assert prc["label"] == "Parameter Rule Check"
    assert prc["status"] in {"PASS", "WARNING", "FAIL", "UNAVAILABLE"}
    assert prc["scope"] == "TDS and turbidity only"
    assert "Laboratory testing is required" in prc["disclaimer"]
    assert set(prc["parameters"].keys()) == {"tds", "turbidity"}
    # Deprecated mirror agrees with the primary result (PASS -> SAFE); the read
    # path carries only safety_status/warning_message mirrors (plan section 3.3)
    assert new_row["safety_status"] == "SAFE"
    assert new_row["warning_message"] is None

    # Historical row: verbatim stored meaning, Phase 10 fields explicitly null
    assert old_row["score_method"] is None
    assert old_row["screening_status"] is None
    assert old_row["parameter_rule_check"] is None
    assert old_row["quality_score"] == 84.6
    assert old_row["prediction"] == "POTABLE"
    assert old_row["safety_status"] == "WARNING"

    # The stored ML verdict endpoint still serves the historical verdict
    # (the new row has no verdict because pH was not measured)
    latest = client.get("/api/predictions/latest")
    assert latest.status_code == 200, latest.text
    assert latest.json()["reading_id"] == historical_id
    assert latest.json()["prediction"] == "POTABLE"
