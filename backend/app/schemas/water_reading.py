from datetime import datetime
from typing import Literal, Optional, List, Dict
from pydantic import BaseModel, Field, ConfigDict, field_validator

from app.schemas.parameter_rule_check import ParameterRuleCheckInfo


class WaterReadingBase(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64, description="Unique identifier of device or simulator")
    # Phase 10: pH/temperature are optional (two-sensor hardware scope).
    # Absent/null = not measured and is stored as NULL - never fabricated.
    # allow_inf_nan=False: non-finite measurements (Infinity/-Infinity/NaN, e.g.
    # from sensor faults or numeric overflow such as 1e999) are rejected at the
    # schema boundary with 422 - they must never reach scoring or storage
    # (an Infinity TDS previously passed ge=0.0 and failed with HTTP 500).
    ph: Optional[float] = Field(None, ge=0.0, le=14.0, allow_inf_nan=False, description="Water pH value (0 to 14); optional - null = not measured")
    tds: float = Field(..., ge=0.0, allow_inf_nan=False, description="Total Dissolved Solids in ppm (>= 0)")
    turbidity: float = Field(..., ge=0.0, allow_inf_nan=False, description="Turbidity in NTU (>= 0)")
    temperature: Optional[float] = Field(None, ge=-10.0, le=100.0, allow_inf_nan=False, description="Water temperature in °C (-10 to 100); optional - null = not measured")
    source: Literal["SIMULATION", "ESP32", "ESP8266"] = Field(..., description="Telemetry source identifier")

    @field_validator("ph", "tds", "turbidity", "temperature", mode="before")
    @classmethod
    def _reject_boolean_as_number(cls, value):
        """Booleans are not measurements: `true` must never be coerced to 1.0."""
        if isinstance(value, bool):
            raise ValueError("numeric sensor value cannot be a boolean")
        return value


class WaterReadingCreate(WaterReadingBase):
    pass


class WaterReadingResponse(WaterReadingBase):
    id: int
    timestamp: datetime
    # Attached assessment indicators (populated from related Prediction record if present)
    quality_score: Optional[float] = None
    # Phase 10 - P1 (SEPARATE): historical vs new assessment separation.
    # score_method is the discriminator: None = historical four-parameter record.
    score_method: Optional[Literal["FOUR_PARAM_LEGACY", "TWO_PARAM_SCREENING"]] = None
    # Screening bands are NOT applicable to historical 4-param scores -> explicit null.
    screening_status: Optional[Literal["GOOD", "MODERATE", "POOR", "UNAVAILABLE"]] = None
    # No per-parameter results are fabricated for historical rows -> explicit null.
    parameter_rule_check: Optional[ParameterRuleCheckInfo] = None
    # Stored verbatim with its original four-parameter meaning for historical rows
    # (never re-mapped to PASS/WARNING/FAIL); deprecated storage mirror for new rows.
    safety_status: Optional[Literal["SAFE", "WARNING", "UNSAFE"]] = None
    warning_message: Optional[str] = None
    prediction: Optional[Literal["POTABLE", "NOT POTABLE"]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    # Explicit null for historical rows (no new ML claim is made for them).
    ml_status: Optional[Literal["AVAILABLE", "UNAVAILABLE"]] = None
    ml_status_reason: Optional[Literal["PH_NOT_MEASURED", "MODEL_UNAVAILABLE", "INFERENCE_FAILED"]] = None

    model_config = ConfigDict(from_attributes=True)


class SafetyInfo(BaseModel):
    """DEPRECATED compatibility mirror (P1): for new records the primary
    assessment is `parameter_rule_check`. Contents reflect the 2-parameter
    rule-check storage mapping (PASS->SAFE, WARNING->WARNING, FAIL->UNSAFE)."""

    status: Literal["SAFE", "WARNING", "UNSAFE"]
    warning_message: Optional[str] = None
    violated_parameters: List[str] = Field(default_factory=list)


class ReadingIngestionResponse(BaseModel):
    # Core Reading Fields (top-level for direct access & backward compatibility)
    id: int
    reading_id: int
    device_id: str
    ph: Optional[float] = None
    tds: float
    turbidity: float
    temperature: Optional[float] = None
    source: Literal["SIMULATION", "ESP32", "ESP8266"]
    timestamp: datetime

    # Two-parameter assessment outputs (Phase 10, plan section 3.2).
    # quality_score is always computable: tds/turbidity are required (422 otherwise).
    quality_score: float
    score_method: Literal["TWO_PARAM_SCREENING", "FOUR_PARAM_LEGACY"]  # REQUIRED column (R-3); new rows only
    screening_status: Literal["GOOD", "MODERATE", "POOR", "UNAVAILABLE"]  # bands from B1 config (R-2)
    screening_explanation: Optional[str] = None
    # PRIMARY assessment for new records (decision P1: SEPARATE).
    parameter_rule_check: ParameterRuleCheckInfo

    # DEPRECATED compatibility mirrors (kept additive for the existing frontend):
    # storage-only mapping for the NOT NULL predictions.safety_status column.
    safety_status: Literal["SAFE", "WARNING", "UNSAFE"]
    warning_message: Optional[str] = None
    safety: SafetyInfo
    reading: WaterReadingResponse

    # ML Inference (Phase 5, EXPERIMENTAL / ADVISORY).
    # Null when the model is unavailable, inference failed, or pH was not
    # measured (inference skipped) - a NULL prediction never means "NOT POTABLE".
    prediction: Optional[Literal["POTABLE", "NOT POTABLE"]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    ml_status: Literal["AVAILABLE", "UNAVAILABLE"] = "AVAILABLE"
    ml_status_reason: Optional[Literal["PH_NOT_MEASURED", "MODEL_UNAVAILABLE", "INFERENCE_FAILED"]] = None
    success: bool = True

    model_config = ConfigDict(from_attributes=True)
