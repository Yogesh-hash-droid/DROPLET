from datetime import datetime, timezone
import logging
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session, joinedload

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
    # 2. Upsert or update device tracking with latest status & RSSI
    device = db.query(Device).filter(Device.device_id == reading_in.device_id).first()
    if not device:
        device_name = f"{reading_in.source.capitalize()} Node ({reading_in.device_id})"
        device = Device(
            device_id=reading_in.device_id,
            device_name=device_name,
            source=DeviceSource(reading_in.source),
            status=DeviceStatus.ONLINE,
            sensor_status=reading_in.sensor_status,
            wifi_rssi=reading_in.wifi_rssi,
            firmware_version=reading_in.firmware_version,
            last_seen=now_utc,
            created_at=now_utc
        )
        db.add(device)
        db.flush()
    else:
        device.last_seen = now_utc
        device.status = DeviceStatus.ONLINE
        device.source = DeviceSource(reading_in.source)
        device.sensor_status = reading_in.sensor_status
        if reading_in.wifi_rssi is not None:
            device.wifi_rssi = reading_in.wifi_rssi
        if reading_in.firmware_version is not None:
            device.firmware_version = reading_in.firmware_version

    # 3. Create reading entity
    db_reading = WaterReading(
        device_id=reading_in.device_id,
        ph=round(float(reading_in.ph), 2) if reading_in.ph is not None else None,
        tds=round(float(reading_in.tds), 2) if reading_in.tds is not None else None,
        turbidity=round(float(reading_in.turbidity), 2) if reading_in.turbidity is not None else None,
        temperature=round(float(reading_in.temperature), 2) if reading_in.temperature is not None else None,
        sensor_status=reading_in.sensor_status,
        wifi_rssi=reading_in.wifi_rssi,
        uptime=reading_in.uptime,
        firmware_version=reading_in.firmware_version,
        source=DeviceSource(reading_in.source),
        timestamp=now_utc
    )
    db.add(db_reading)
    db.flush()  # Generates db_reading.id

    # 4. Check if sensor values are in fault state
    if reading_in.sensor_status != "ok" or db_reading.tds is None or db_reading.turbidity is None:
        # Fault state: Do NOT calculate rule checks or screening scores or run ML.
        from app.models.prediction import SafetyStatus as PredictionSafetyStatus
        _SENSOR_FAULT_MESSAGES = {
            "ads1115_not_found": "ADS1115 ADC not found on I2C bus — verify SDA/SCL wiring and ADDR pin",
            "read_error": "Sensor read error during ADC conversion — check wiring stability",
            "serial_fault": "Serial sensor data unavailable — Arduino Uno may not be transmitting",
        }
        fault_warning = _SENSOR_FAULT_MESSAGES.get(
            reading_in.sensor_status,
            f"Sensor subsystem offline ({reading_in.sensor_status})"
        )
        db_prediction = Prediction(
            reading_id=db_reading.id,
            prediction=None,
            confidence=None,
            quality_score=None,
            safety_status=PredictionSafetyStatus.WARNING,
            warning_message=fault_warning,
            score_method=ScoreMethod.TWO_PARAM_SCREENING,
            timestamp=now_utc
        )
        db.add(db_prediction)
        db.commit()
        db.refresh(db_reading)
        return db_reading, None, None, None, "UNAVAILABLE", "SENSOR_FAULT"

    # 5. Normal operation: Parameter Rule Check
    rule_result = safety_service.evaluate_parameter_rule_check(
        tds=db_reading.tds,
        turbidity=db_reading.turbidity,
        config=config
    )

    # 6. Two-parameter screening score (0-100, configurable bands - B1)
    screening_result = quality_service.calculate_screening_score(
        tds=db_reading.tds,
        turbidity=db_reading.turbidity,
        config=config
    )

    # 7. Conditional ML Inference (Phase 5 - EXPERIMENTAL / ADVISORY).
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
        except Exception as exc:  # noqa: BLE001
            logger.error("ML inference step failed, storing NULL prediction: %s", exc)
            ml_result = None
        if ml_result is None:
            ml_status = "UNAVAILABLE"
            ml_status_reason = (
                "MODEL_UNAVAILABLE" if ml_service.get_ml_service().last_error
                else "INFERENCE_FAILED"
            )

    # 8. Store assessment record in predictions table
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
    """Retrieve the most recent water reading with assessment eagerly loaded."""
    return (
        db.query(WaterReading)
        .options(joinedload(WaterReading.assessment))
        .order_by(WaterReading.timestamp.desc(), WaterReading.id.desc())
        .first()
    )


def get_readings_history(
    db: Session,
    limit: int = 100,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> List[WaterReading]:
    """
    Retrieve historical water readings ordered newest first.
    Eagerly loads the assessment relationship via a single SQL JOIN (no N+1).
    """
    query = db.query(WaterReading).options(joinedload(WaterReading.assessment))

    if start_date:
        query = query.filter(WaterReading.timestamp >= start_date)
    if end_date:
        query = query.filter(WaterReading.timestamp <= end_date)

    return query.order_by(WaterReading.timestamp.desc(), WaterReading.id.desc()).limit(limit).all()
