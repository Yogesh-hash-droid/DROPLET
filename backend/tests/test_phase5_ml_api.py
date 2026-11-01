"""
Phase 5 tests: ML inference service + API integration (EXPERIMENTAL / ADVISORY).

Covers: model loading, valid prediction, prediction labels, confidence range,
POST /api/readings with ML, persistence, GET /api/predictions/latest,
safety/ML disagreement, ML failure handling and Phase 1-4 regression.

The deterministic assessment stays authoritative in every case - no test ever
lets the ML verdict change `safety_status` or the screening score.

PHASE 10 RETARGET (documented per plan section 9): tests 8, 10 and 11 were
rewritten because the deterministic assessment now evaluates TDS + turbidity
only (Parameter Rule Check); pH and temperature no longer affect it.
API tests below use the live MySQL database (dependency overrides cleared) -
they are BLOCKED until the separately approved migration runs.
"""
import inspect

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.database import SessionLocal, check_db_connection
from app.ml import service as ml_service_module
from app.ml.service import (
    FEATURE_COLUMNS,
    MLInferenceResult,
    MLServiceError,
    MLInferenceService,
    get_ml_service,
)
from app.models.prediction import Prediction, SafetyStatus
from app.services import config_service, safety_service

app.dependency_overrides.clear()
client = TestClient(app)

ALLOWED_LABELS = {"POTABLE", "NOT POTABLE"}


def _reading(device_id: str, ph: float, tds: float, turbidity: float, temperature: float = 25.0):
    return {
        "device_id": device_id,
        "ph": ph,
        "tds": tds,
        "turbidity": turbidity,
        "temperature": temperature,
        "source": "SIMULATION",
    }


# ------------------------------------------------------------------ service ---
def test_db_connected():
    assert check_db_connection() is True


def test_ml_service_loads_model_once():
    """1. The artifact is loaded lazily and reused (not per request)."""
    service = get_ml_service()
    assert service.model_path.exists(), f"missing artifact: {service.model_path}"

    payload_a = service.load()
    payload_b = service.load()
    assert payload_a is payload_b, "artifact must be loaded once and cached"
    assert tuple(payload_a["feature_columns"]) == FEATURE_COLUMNS == ("ph", "tds", "turbidity")
    assert payload_a["temperature_used"] is False
    assert service.is_loaded is True
    assert service.last_error is None


def test_ml_service_valid_prediction():
    """2. Valid record -> label + probability confidence in [0, 1]."""
    result = get_ml_service().predict(ph=7.1, tds=220.0, turbidity=1.5)
    assert isinstance(result, MLInferenceResult)
    assert result.prediction in ALLOWED_LABELS
    assert 0.0 <= result.confidence <= 1.0
    assert set(result.probabilities) == ALLOWED_LABELS
    assert abs(sum(result.probabilities.values()) - 1.0) < 1e-6
    assert result.confidence == pytest.approx(max(result.probabilities.values()), abs=1e-6)
    assert result.status == "EXPERIMENTAL"


def test_ml_model_excludes_temperature():
    """3. Exactly ph/tds/turbidity are passed - temperature never is."""
    signature = inspect.signature(MLInferenceService.predict)
    assert list(signature.parameters) == ["self", "ph", "tds", "turbidity"]

    model = get_ml_service().load()["model"]
    assert list(model.feature_names_in_) == ["ph", "tds", "turbidity"]

    result = get_ml_service().predict(ph=7.0, tds=250.0, turbidity=1.0)
    assert set(result.features) == {"ph", "tds", "turbidity"}
    assert "temperature" not in result.features


def test_ml_invalid_input_rejected(tmp_path):
    """4. Invalid inputs / missing artifact raise - never fabricated values."""
    with pytest.raises(MLServiceError):
        get_ml_service().predict(ph=15.0, tds=250.0, turbidity=1.0)
    with pytest.raises(MLServiceError):
        get_ml_service().predict(ph=7.0, tds=-5.0, turbidity=1.0)
    with pytest.raises(MLServiceError):
        get_ml_service().predict(ph=None, tds=250.0, turbidity=1.0)

    broken = MLInferenceService(model_path=tmp_path / "does-not-exist.joblib")
    with pytest.raises(MLServiceError):
        broken.predict(ph=7.0, tds=250.0, turbidity=1.0)
    assert broken.is_loaded is False
    assert broken.last_error is not None


# ------------------------------------------------------------ POST /readings --
def test_post_reading_with_ml_returns_prediction():
    """5. POST /api/readings returns a real ML prediction + confidence."""
    payload = _reading("PHASE5-ML-001", ph=7.1, tds=220.0, turbidity=1.5, temperature=26.5)
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()

    assert data["prediction"] in ALLOWED_LABELS
    assert 0.0 <= data["confidence"] <= 1.0
    assert data["reading"]["prediction"] in ALLOWED_LABELS
    assert 0.0 <= data["reading"]["confidence"] <= 1.0
    # Safety unchanged by ML
    assert data["safety_status"] == "SAFE"
    assert data["safety"]["status"] == "SAFE"
    assert 0.0 <= data["quality_score"] <= 100.0


def test_ml_result_persisted_in_mysql():
    """6. The ML verdict is stored in the existing predictions table."""
    payload = _reading("PHASE5-ML-002", ph=7.4, tds=480.0, turbidity=4.5)
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()

    db: Session = SessionLocal()
    try:
        row = db.query(Prediction).filter(Prediction.reading_id == data["reading_id"]).first()
        assert row is not None
        assert row.prediction is not None
        assert row.prediction.value in ALLOWED_LABELS
        assert row.confidence is not None
        assert 0.0 <= row.confidence <= 1.0
        assert row.prediction.value == data["prediction"]
        assert row.confidence == pytest.approx(data["confidence"], abs=1e-4)
        # Rule engine verdict stored alongside (independent columns)
        assert row.safety_status == SafetyStatus.SAFE
        assert row.quality_score == pytest.approx(data["quality_score"], abs=0.01)
    finally:
        db.close()


def test_get_predictions_latest():
    """7. GET /api/predictions/latest returns the latest stored ML verdict."""
    res = client.get("/api/predictions/latest")
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["prediction"] in ALLOWED_LABELS
    assert 0.0 <= data["confidence"] <= 1.0
    assert data["ml_status"] == "EXPERIMENTAL"
    assert "EXPERIMENTAL" in data["disclaimer"]
    assert "not a guarantee" in data["disclaimer"].lower()
    assert data["temperature_used"] is False
    # Exactly the model's three inputs, never temperature
    assert set(data["input_features"]) == {"ph", "tds", "turbidity"}
    assert data["safety_status"] in {"SAFE", "WARNING", "UNSAFE"}
    assert data["quality_score"] >= 0.0
    assert data["reading_id"] > 0

    latest_reading = client.get("/api/readings/latest").json()
    assert data["reading_id"] == latest_reading["id"]


# ------------------------------------------------- safety vs ML separation ----
def test_safety_unsafe_ml_potable_disagreement():
    """8. Phase 10 RETARGET: pH alone no longer drives the deterministic
    assessment (TDS + turbidity only), while ML still reports its verdict as-is.

    Old premise (pH 5.5 -> UNSAFE) is obsolete: pH is not evaluated by the
    Parameter Rule Check, so the record reads PASS/SAFE with no violations.
    """
    payload = _reading("PHASE5-CLASH-001", ph=5.5, tds=200.0, turbidity=1.0)
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()

    # Deterministic outputs: TDS 200 <= 500 ppm and turbidity 1.0 <= 5.0 NTU -> PASS
    assert data["parameter_rule_check"]["status"] == "PASS"
    assert data["safety_status"] == "SAFE"            # DEPRECATED storage mirror (PASS -> SAFE)
    assert data["safety"]["status"] == "SAFE"
    assert data["safety"]["violated_parameters"] == []
    assert data["score_method"] == "TWO_PARAM_SCREENING"

    # The ML verdict is reported as-is
    assert data["prediction"] in ALLOWED_LABELS
    assert 0.0 <= data["confidence"] <= 1.0

    # Independent recomputation proves the deterministic output was not influenced
    db: Session = SessionLocal()
    try:
        config = config_service.get_system_config(db)
        expected = safety_service.evaluate_parameter_rule_check(
            tds=200.0, turbidity=1.0, config=config
        )
    finally:
        db.close()
    assert expected.status == "PASS"
    assert data["parameter_rule_check"]["status"] == expected.status
    assert data["safety_status"] == expected.storage_status.value
    if data["prediction"] == "POTABLE":
        # explicit disagreement case: both results returned, assessment untouched
        assert data["safety_status"] == "SAFE"


def test_safety_safe_ml_not_potable_disagreement():
    """9. In-range water can still be flagged NOT POTABLE by the model."""
    payload = _reading("PHASE5-CLASH-002", ph=7.4, tds=480.0, turbidity=4.5)
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()

    assert data["safety_status"] == "SAFE"
    assert data["safety"]["violated_parameters"] == []
    assert data["prediction"] in ALLOWED_LABELS
    assert 0.0 <= data["confidence"] <= 1.0


def test_temperature_unsafe_ml_potable_disagreement():
    """10. Phase 10 RETARGET: temperature is no longer evaluated by the
    deterministic assessment (two-sensor scope), so a 60 °C reading no longer
    produces UNSAFE - it has no effect at all. ML never sees temperature either.
    """
    payload = _reading("PHASE5-CLASH-003", ph=7.2, tds=200.0, turbidity=1.0, temperature=60.0)
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()

    assert data["parameter_rule_check"]["status"] == "PASS"
    assert data["safety_status"] == "SAFE"
    assert data["safety"]["violated_parameters"] == []
    assert "Temperature" not in data["safety"]["violated_parameters"]
    # ML never sees temperature
    assert data["prediction"] in ALLOWED_LABELS
    assert 0.0 <= data["confidence"] <= 1.0


# ---------------------------------------------------------- failure handling --
def test_ml_failure_keeps_safety_working(monkeypatch):
    """11. If ML inference explodes, the deterministic assessment still works and
    ML fields are null (Phase 10: violations = TDS/turbidity only; the verdict is
    accompanied by an explicit UNAVAILABLE status, never a fake label)."""
    original_predict_reading = ml_service_module.predict_reading

    def _boom(**kwargs):
        raise RuntimeError("simulated model outage")

    # Layer 1: the ML wrapper itself fails unexpectedly
    monkeypatch.setattr(ml_service_module, "predict_reading", _boom)

    payload = _reading("PHASE5-FAIL-001", ph=3.5, tds=1000.0, turbidity=80.0, temperature=50.0)
    res = client.post("/api/readings", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()

    assert data["success"] is True
    # TDS 1000 > 750 and turbidity 80 > 10 -> overall FAIL -> mirror UNSAFE;
    # pH and temperature are not evaluated any more (plan section 9 retarget).
    assert data["parameter_rule_check"]["status"] == "FAIL"
    assert data["safety_status"] == "UNSAFE"
    assert set(data["safety"]["violated_parameters"]) == {"TDS", "Turbidity"}
    assert "pH" not in data["safety"]["violated_parameters"]
    assert 0.0 <= data["quality_score"] <= 100.0
    assert data["prediction"] is None
    assert data["confidence"] is None
    assert data["ml_status"] == "UNAVAILABLE"
    assert data["ml_status_reason"] in {"MODEL_UNAVAILABLE", "INFERENCE_FAILED"}

    db: Session = SessionLocal()
    try:
        row = db.query(Prediction).filter(Prediction.reading_id == data["reading_id"]).first()
        assert row is not None
        assert row.prediction is None
        assert row.confidence is None
        assert row.safety_status == SafetyStatus.UNSAFE
        assert row.score_method is not None          # new rows are tagged (R-3)
    finally:
        db.close()

    # Layer 2: inference raises inside the service - the wrapper degrades to None
    monkeypatch.setattr(ml_service_module, "predict_reading", original_predict_reading)

    def _infer_failure(self, **kwargs):
        raise MLServiceError("simulated inference failure")

    monkeypatch.setattr(ml_service_module.MLInferenceService, "predict", _infer_failure)

    payload_2 = _reading("PHASE5-FAIL-002", ph=7.1, tds=220.0, turbidity=1.5, temperature=26.5)
    res_2 = client.post("/api/readings", json=payload_2)
    assert res_2.status_code == 201, res_2.text
    data_2 = res_2.json()
    assert data_2["safety_status"] == "SAFE"
    assert data_2["parameter_rule_check"]["status"] == "PASS"
    assert data_2["prediction"] is None
    assert data_2["confidence"] is None
    assert data_2["ml_status"] == "UNAVAILABLE"
    assert data_2["ml_status_reason"] in {"MODEL_UNAVAILABLE", "INFERENCE_FAILED"}

    # Previously stored predictions remain readable (NULL rows are excluded)
    latest = client.get("/api/predictions/latest")
    assert latest.status_code == 200
    assert latest.json()["prediction"] in ALLOWED_LABELS


def test_safety_rule_engine_remains_authoritative():
    """12. Every stored row keeps the rule-engine safety status, never an ML one."""
    db: Session = SessionLocal()
    try:
        rows = (
            db.query(Prediction)
            .filter(Prediction.prediction.isnot(None))
            .order_by(Prediction.id.desc())
            .limit(25)
            .all()
        )
        assert rows, "expected stored ML predictions"
        for row in rows:
            assert row.safety_status in {
                SafetyStatus.SAFE,
                SafetyStatus.WARNING,
                SafetyStatus.UNSAFE,
            }
            assert 0.0 <= row.confidence <= 1.0
            assert row.prediction.value in ALLOWED_LABELS
    finally:
        db.close()


def test_ml_response_schema_rejects_invalid_values():
    """13. Endpoint shape is validated by schema constraints (confidence bounds)."""
    from app.schemas.prediction import LatestPredictionResponse
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        LatestPredictionResponse(
            id=1,
            reading_id=1,
            prediction="POTABLE",
            confidence=1.5,  # out of range -> rejected
            quality_score=90.0,
            safety_status="SAFE",
            timestamp="2026-10-06T00:00:00",
            disclaimer="d",
        )
    with pytest.raises(pydantic.ValidationError):
        LatestPredictionResponse(
            id=1,
            reading_id=1,
            prediction="MAYBE",  # unknown label -> rejected
            confidence=0.5,
            quality_score=90.0,
            safety_status="SAFE",
            timestamp="2026-10-06T00:00:00",
            disclaimer="d",
        )
