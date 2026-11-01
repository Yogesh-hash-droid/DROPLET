from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.ml.service import ML_DISCLAIMER
from app.models.prediction import Prediction
from app.schemas.prediction import LatestPredictionResponse

router = APIRouter(prefix="/predictions", tags=["Predictions"])


@router.get(
    "/latest",
    response_model=LatestPredictionResponse,
    summary="Retrieve the latest stored ML potability prediction"
)
def get_latest_prediction_endpoint(db: Session = Depends(get_db)):
    """
    Return the most recent stored ML verdict (`prediction` + `confidence`).

    EXPERIMENTAL / ADVISORY: the model is weak (test ROC-AUC 0.5522) and never
    certifies water. The Safety Rule Engine remains authoritative - the safety
    status returned here comes from the rule engine, not from the model.
    Returns HTTP 404 when no ML prediction has been stored yet (e.g. model
    unavailable for every reading so far).
    """
    row = (
        db.query(Prediction)
        .filter(Prediction.prediction.isnot(None), Prediction.confidence.isnot(None))
        .order_by(Prediction.timestamp.desc(), Prediction.id.desc())
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ML prediction stored yet."
        )

    confidence = float(row.confidence)
    if not 0.0 <= confidence <= 1.0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stored confidence out of range: {confidence}"
        )

    reading = row.reading
    pred_val = getattr(row.prediction, "value", str(row.prediction)) if row.prediction else None
    safety_val = getattr(row.safety_status, "value", str(row.safety_status)) if row.safety_status else "SAFE"

    return LatestPredictionResponse(
        id=row.id,
        reading_id=row.reading_id,
        prediction=pred_val,
        confidence=confidence,
        quality_score=row.quality_score,
        safety_status=safety_val,
        warning_message=row.warning_message,
        input_features=(
            {"ph": reading.ph, "tds": reading.tds, "turbidity": reading.turbidity}
            if reading else {}
        ),
        temperature_used=False,
        ml_status="EXPERIMENTAL",
        disclaimer=ML_DISCLAIMER,
        timestamp=row.timestamp,
    )
