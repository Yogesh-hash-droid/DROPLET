from datetime import datetime
from typing import Dict, Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


class PredictionResponse(BaseModel):
    id: int
    reading_id: int
    prediction: Literal["POTABLE", "NOT POTABLE"]
    confidence: float
    quality_score: float
    safety_status: Literal["SAFE", "WARNING", "UNSAFE"]
    warning_message: Optional[str] = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class LatestPredictionResponse(PredictionResponse):
    """Latest stored ML prediction (EXPERIMENTAL / ADVISORY)."""

    confidence: float = Field(..., ge=0.0, le=1.0, description="Model probability of `prediction`, 0-1")
    input_features: Dict[str, float] = Field(
        default_factory=dict,
        description="Sensor values fed to the model (ph, tds, turbidity)",
    )
    temperature_used: bool = Field(
        False,
        description="Always false: temperature is not a feature of this model",
    )
    ml_status: str = Field("EXPERIMENTAL", description="Advisory status of the ML verdict")
    disclaimer: str
