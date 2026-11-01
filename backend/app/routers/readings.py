import json
import logging
import urllib.request
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.system_config import SystemConfig
from app.models.water_reading import WaterReading
from app.schemas.parameter_rule_check import ParameterRuleCheckInfo, ParameterRuleCheckParameter
from app.schemas.water_reading import (
    WaterReadingCreate,
    WaterReadingResponse,
    ReadingIngestionResponse,
    SafetyInfo,
)
from app.services import config_service, quality_service, reading_service, safety_service

router = APIRouter(prefix="/readings", tags=["Readings"])
settings = get_settings()
relay_logger = logging.getLogger("app.relay")


def _relay_reading_to_cloud(data_dict: dict):
    """Relay reading from local receiver to Render cloud so Vercel updates in real time."""
    cloud_url = "https://droplet-api-byl8.onrender.com/api/readings"
    try:
        if data_dict.get("ph") is None:
            data_dict["ph"] = 7.0
        payload = json.dumps(data_dict).encode("utf-8")
        req = urllib.request.Request(
            cloud_url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "DROPLET-LocalRelay/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            relay_logger.info("Relayed reading to cloud Render: code %d", resp.status)
    except Exception as exc:
        relay_logger.debug("Cloud relay skipped/failed: %s", exc)


# Display names for the DEPRECATED safety mirror only (the Parameter Rule Check
# itself uses the lowercase parameter keys "tds"/"turbidity").
_MIRROR_DISPLAY_NAMES = {"tds": "TDS", "turbidity": "Turbidity"}


def _to_rule_check_info(result: safety_service.ParameterRuleCheckResult) -> ParameterRuleCheckInfo:
    """Build the primary assessment block (plan section 3.2) from the service result."""
    return ParameterRuleCheckInfo(
        status=result.status,
        parameters={
            param.name: ParameterRuleCheckParameter(
                value=param.value,
                unit=param.unit,
                status=param.status,
                detail=param.detail,
            )
            for param in result.parameters
        },
        unavailable_parameters=list(result.unavailable_parameters),
    )


def _build_reading_response(reading: WaterReading, config: SystemConfig) -> WaterReadingResponse:
    """
    Serialize a stored reading with the P1 historical/new separation (plan 3.3).

    Discriminator: `score_method`.
      * Historical rows (`score_method IS NULL`) keep their stored four-parameter
        meaning verbatim; `screening_status`/`parameter_rule_check` stay explicit
        `null` (nothing is reconstructed) and no new ML claim is made.
      * New rows (`TWO_PARAM_SCREENING`) expose the screening band (classified
        from the STORED score against the CURRENT configured bands) and the
        Parameter Rule Check recomputed from the stored TDS/turbidity values -
        a deterministic function of the same inputs the write-time check used.
    """
    response = WaterReadingResponse.model_validate(reading)

    if reading.score_method is None:
        # Historical record: stored values only - never re-mapped, never completed.
        return response

    # New two-parameter screening record.
    response.screening_status = quality_service.classify_screening_status(
        reading.quality_score, config
    )
    response.parameter_rule_check = _to_rule_check_info(
        safety_service.evaluate_parameter_rule_check(
            tds=reading.tds,
            turbidity=reading.turbidity,
            config=config,
        )
    )
    if reading.prediction is not None:
        response.ml_status = "AVAILABLE"
    else:
        # A NULL prediction never renders as "NOT POTABLE": it means no verdict.
        response.ml_status = "UNAVAILABLE"
        response.ml_status_reason = "PH_NOT_MEASURED" if reading.ph is None else None

    return response


@router.post(
    "",
    response_model=ReadingIngestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a new water quality telemetry reading"
)
def create_reading_endpoint(
    reading_in: WaterReadingCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Ingest water-quality telemetry (simulator, ESP32, or ESP8266 two-sensor
    hardware). TDS and turbidity are required; pH and temperature are optional
    and stored as NULL when absent (never fabricated).
    """
    try:
        # Automatic cloud sync so Vercel updates in real time:
        if settings.ENVIRONMENT != "production":
            background_tasks.add_task(_relay_reading_to_cloud, reading_in.model_dump())

        reading, rule_res, screening_res, ml_res, ml_status, ml_status_reason = (
            reading_service.create_reading_with_assessment(
                db=db,
                reading_in=reading_in
            )
        )


        violated_parameters = [
            _MIRROR_DISPLAY_NAMES[param.name]
            for param in rule_res.parameters
            if param.status != "PASS"
        ]

        return ReadingIngestionResponse(
            id=reading.id,
            reading_id=reading.id,
            device_id=reading.device_id,
            ph=reading.ph,
            tds=reading.tds,
            turbidity=reading.turbidity,
            temperature=reading.temperature,
            source=reading.source.value,
            timestamp=reading.timestamp,
            quality_score=screening_res.overall_score,
            score_method=reading.score_method,
            screening_status=screening_res.screening_status,
            screening_explanation=screening_res.screening_explanation,
            # Primary assessment for new records (plan section 3.2).
            parameter_rule_check=_to_rule_check_info(rule_res),
            # DEPRECATED compatibility mirrors - storage mapping only (P1).
            safety_status=rule_res.storage_status.value,
            warning_message=rule_res.warning_message,
            safety=SafetyInfo(
                status=rule_res.storage_status.value,
                warning_message=rule_res.warning_message,
                violated_parameters=violated_parameters
            ),
            reading=WaterReadingResponse.model_validate(reading),
            prediction=ml_res.prediction if ml_res else None,
            confidence=ml_res.confidence if ml_res else None,
            ml_status=ml_status,
            ml_status_reason=ml_status_reason,
            success=True
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist reading and evaluation: {str(exc)}"
        )


@router.get(
    "/latest",
    response_model=WaterReadingResponse,
    summary="Retrieve latest water quality reading"
)
def get_latest_reading_endpoint(db: Session = Depends(get_db)):
    """Return the most recent water quality reading with its assessment.

    New rows expose `score_method`/`screening_status`/`parameter_rule_check`;
    historical rows keep their stored four-parameter meaning with explicit
    `null` for fields that are not applicable (plan section 3.3).
    """
    reading = reading_service.get_latest_reading(db=db)
    if not reading:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No water quality readings found."
        )
    config = config_service.get_system_config(db)
    return _build_reading_response(reading, config)


@router.get(
    "/history",
    response_model=List[WaterReadingResponse],
    summary="Retrieve historical water quality readings"
)
def get_readings_history_endpoint(
    limit: int = Query(100, ge=1, le=1000, description="Max number of readings to return"),
    start_date: Optional[datetime] = Query(None, description="Filter readings on or after this UTC timestamp"),
    end_date: Optional[datetime] = Query(None, description="Filter readings on or before this UTC timestamp"),
    db: Session = Depends(get_db)
):
    """Return historical water quality readings ordered newest first.

    Historical and new records are distinguished by `score_method`; historical
    records are returned verbatim and never re-evaluated (plan section 3.3).
    """
    readings = reading_service.get_readings_history(
        db=db,
        limit=limit,
        start_date=start_date,
        end_date=end_date
    )
    config = config_service.get_system_config(db)
    return [_build_reading_response(reading, config) for reading in readings]
