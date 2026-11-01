from datetime import datetime, timezone
import logging
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.ml import service as ml_service
from app.ml.service import MLInferenceResult
from app.models.device import Device, DeviceStatus, DeviceSource
from app.models.water_reading import WaterReading
from app.models.prediction import Prediction, PotabilityResult, ScoreMethod
from app.schemas.water_reading import WaterReadingCreate
from app.services import config_service, safety_service, quality_service

logger = logging.getLogger("app.readings")


def create_reading_with_assessment(
    db: Session,
    reading_in: WaterReadingCreate
) -> Tuple[
    WaterReading,
    safety_service.ParameterRuleCheckResult,
    quality_service.ScreeningScoreResult,
    Optional[MLInferenceResult],
    str,                  # ml_status: "AVAILABLE" | "UNAVAILABLE"
    Optional[str],        # ml_status_reason: None | PH_NOT_MEASURED | MODEL_UNAVAILABLE | INFERENCE_FAILED
]:
    """
    Validates and stores a new water quality telemetry record.

    Phase 10 (two-sensor scope):
      * pH/temperature are optional -> stored as NULL when absent (never fabricated).
      * Parameter Rule Check (TDS + turbidity only) is the primary assessment;
        its storage mirror satisfies the NOT NULL safety_status column (P1).
      * Two-parameter screening score with configurable bands (B1) replaces the
        four-parameter score for NEW rows; score_method = TWO_PARAM_SCREENING.
      * ML inference is conditional: pH absent -> model never invoked, verdict
        NULL with explicit reason PH_NOT_MEASURED.
      * No existing row is ever UPDATEd or DELETEd.

    Safety and ML are independent: a POTABLE model verdict never changes the
    rule-check status, and an ML failure never blocks the assessment.
    """
    now_utc = datetime.now(timezone.utc)

    # 1. Retrieve active configuration thresholds
    config = config_service.get_system_config(db)

    # 2. Upsert or update device tracking
    device = db.query(Device).filter(Device.device_id == reading_in.device_id).first()
    if not device:
        device_name = f"{reading_in.source.capitalize()} Node ({reading_in.device_id})"
        device = Device(
            device_id=reading_in.device_id,
            device_name=device_name,
            source=DeviceSource(reading_in.source),
            status=DeviceStatus.ONLINE,
            last_seen=now_utc,
            created_at=now_utc
        )
        db.add(device)
        db.flush()
    else:
        device.last_seen = now_utc
        device.status = DeviceStatus.ONLINE
        device.source = DeviceSource(reading_in.source)

    # 3. Create reading entity - optional values round ONLY when present.
    #    Missing pH/temperature are persisted as SQL NULL, never defaulted.
    db_reading = WaterReading(
        device_id=reading_in.device_id,
        ph=round(float(reading_in.ph), 2) if reading_in.ph is not None else None,
        tds=round(float(reading_in.tds), 2),
        turbidity=round(float(reading_in.turbidity), 2),
        temperature=round(float(reading_in.temperature), 2) if reading_in.temperature is not None else None,
        source=DeviceSource(reading_in.source),
        timestamp=now_utc
    )
    db.add(db_reading)
    db.flush()  # Generates db_reading.id

    # 4. Parameter Rule Check - TDS + turbidity only (primary assessment for
    #    new records). Storage mirror keeps the NOT NULL column satisfied.
    rule_result = safety_service.evaluate_parameter_rule_check(
        tds=db_reading.tds,
        turbidity=db_reading.turbidity,
        config=config
    )

    # 5. Two-parameter screening score (0-100, configurable bands - B1)
    screening_result = quality_service.calculate_screening_score(
        tds=db_reading.tds,
        turbidity=db_reading.turbidity,
        config=config
    )

    # 6. Conditional ML Inference (Phase 5 - EXPERIMENTAL / ADVISORY).
    #    pH absent -> the model is NEVER invoked and no pH is fabricated:
    #    verdict stays NULL with reason PH_NOT_MEASURED.
    #    Guarded twice: the ML wrapper swallows its own errors, and this block
    #    guarantees that no ML failure can ever break the assessment flow.
    # 6. ML Inference (Phase 5 - EXPERIMENTAL / ADVISORY).
    # Uses measured pH, or standard neutral drinking water baseline (7.0) when hardware
    # only has TDS/turbidity probes, ensuring ML potability prediction is active.
    ml_status: str = "AVAILABLE"
    ml_status_reason: Optional[str] = None
    ml_result: Optional[MLInferenceResult] = None

    if db_reading.ph is None:
        ml_status = "UNAVAILABLE"
        ml_status_reason = "PH_NOT_MEASURED"
    else:
        try:
            ml_result = ml_service.predict_reading(
                ph=db_reading.ph,
                tds=db_reading.tds,
                turbidity=db_reading.turbidity,
            )
        except Exception as exc:  # noqa: BLE001 - assessment must never depend on ML
            logger.error("ML inference step failed, storing NULL prediction: %s", exc)
            ml_result = None
        if ml_result is None:
            ml_status = "UNAVAILABLE"
            ml_status_reason = (
                "MODEL_UNAVAILABLE" if ml_service.get_ml_service().last_error
                else "INFERENCE_FAILED"
            )


    # 7. Store assessment record in the predictions table (single existing table:
    #    prediction/confidence hold the ML verdict, or NULL when ML did not run;
    #    score_method marks this as a new two-parameter screening record - R-3)
    db_prediction = Prediction(
        reading_id=db_reading.id,
        prediction=PotabilityResult(ml_result.prediction) if ml_result else None,
        confidence=float(ml_result.confidence) if ml_result else None,
        quality_score=screening_result.overall_score,
        safety_status=rule_result.storage_status,
        warning_message=rule_result.warning_message,
        score_method=ScoreMethod.TWO_PARAM_SCREENING,
        timestamp=now_utc
    )
    db.add(db_prediction)
    db.commit()

    db.refresh(db_reading)
    return db_reading, rule_result, screening_result, ml_result, ml_status, ml_status_reason


def get_latest_reading(db: Session) -> Optional[WaterReading]:
    """Retrieve the most recent water reading."""
    return db.query(WaterReading).order_by(WaterReading.timestamp.desc(), WaterReading.id.desc()).first()


def get_readings_history(
    db: Session,
    limit: int = 100,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> List[WaterReading]:
    """
    Retrieve historical water readings ordered newest first.
    Optionally filter by start and end timestamps.
    """
    query = db.query(WaterReading)

    if start_date:
        query = query.filter(WaterReading.timestamp >= start_date)
    if end_date:
        query = query.filter(WaterReading.timestamp <= end_date)

    return query.order_by(WaterReading.timestamp.desc(), WaterReading.id.desc()).limit(limit).all()
