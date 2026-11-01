from datetime import datetime
from typing import Literal, Optional, List, Dict
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from app.schemas.parameter_rule_check import ParameterRuleCheckInfo


class WaterReadingBase(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64, description="Unique identifier of device or simulator")
    # In fault-tolerant telemetry, sensor values are floats when valid, or null when faulty/unmeasured.
    # Non-finite values (Inf/NaN) are rejected.
    ph: Optional[float] = Field(None, ge=0.0, le=14.0, allow_inf_nan=False, description="Water pH value (0 to 14); optional - null = not measured")
    tds: Optional[float] = Field(None, ge=0.0, allow_inf_nan=False, description="Total Dissolved Solids in ppm (>= 0); null when sensor faulty")
    turbidity: Optional[float] = Field(None, ge=0.0, allow_inf_nan=False, description="Turbidity in NTU (>= 0); null when sensor faulty")
    temperature: Optional[float] = Field(None, ge=-10.0, le=100.0, allow_inf_nan=False, description="Water temperature in °C (-10 to 100); optional - null = not measured")
    source: Literal["SIMULATION", "ESP32", "ESP8266"] = Field(..., description="Telemetry source identifier")
    sensor_status: Literal["ok", "ads1115_not_found", "read_error"] = Field("ok", description="Operational status of the sensor subsystem")
    wifi_rssi: Optional[int] = Field(None, description="Wi-Fi signal strength in dBm")
    uptime: Optional[int] = Field(None, description="Device uptime in seconds")
    firmware_version: Optional[str] = Field(None, max_length=32, description="Firmware version string")

    @field_validator("ph", "tds", "turbidity", "temperature", mode="before")
    @classmethod
    def _reject_boolean_as_number(cls, value):
        """Booleans are not measurements: `true` must never be coerced to 1.0."""
        if isinstance(value, bool):
            raise ValueError("numeric sensor value cannot be a boolean")
        return value

    @model_validator(mode="after")
    def validate_sensor_status_and_readings(self):
        if self.sensor_status == "ok":
            if self.tds is None:
                raise ValueError("tds is required when sensor_status is ok")
            if self.turbidity is None:
                raise ValueError("turbidity is required when sensor_status is ok")
        return self


class WaterReadingCreate(WaterReadingBase):
    pass


class WaterReadingResponse(WaterReadingBase):
    id: int
    timestamp: datetime
    # Attached assessment indicators (populated from related Prediction record if present)
    quality_score: Optional[float] = None
    score_method: Optional[Literal["FOUR_PARAM_LEGACY", "TWO_PARAM_SCREENING"]] = None
    screening_status: Optional[Literal["GOOD", "MODERATE", "POOR", "UNAVAILABLE"]] = None
    parameter_rule_check: Optional[ParameterRuleCheckInfo] = None
    safety_status: Optional[Literal["SAFE", "WARNING", "UNSAFE"]] = None
    warning_message: Optional[str] = None
    prediction: Optional[Literal["POTABLE", "NOT POTABLE"]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    ml_status: Optional[Literal["AVAILABLE", "UNAVAILABLE"]] = None
    ml_status_reason: Optional[Literal["PH_NOT_MEASURED", "MODEL_UNAVAILABLE", "INFERENCE_FAILED", "SENSOR_FAULT"]] = None

    model_config = ConfigDict(from_attributes=True)


class SafetyInfo(BaseModel):
    status: Literal["SAFE", "WARNING", "UNSAFE"]
    warning_message: Optional[str] = None
    violated_parameters: List[str] = Field(default_factory=list)


class ReadingIngestionResponse(BaseModel):
    id: int
    reading_id: int
    device_id: str
    ph: Optional[float] = None
    tds: Optional[float] = None
    turbidity: Optional[float] = None
    temperature: Optional[float] = None
    source: Literal["SIMULATION", "ESP32", "ESP8266"]
    timestamp: datetime

    quality_score: Optional[float] = None
    score_method: Optional[Literal["TWO_PARAM_SCREENING", "FOUR_PARAM_LEGACY"]] = None
    screening_status: Optional[Literal["GOOD", "MODERATE", "POOR", "UNAVAILABLE"]] = None
    screening_explanation: Optional[str] = None
    parameter_rule_check: Optional[ParameterRuleCheckInfo] = None

    safety_status: Optional[Literal["SAFE", "WARNING", "UNSAFE"]] = None
    warning_message: Optional[str] = None
    safety: Optional[SafetyInfo] = None
    reading: WaterReadingResponse

    prediction: Optional[Literal["POTABLE", "NOT POTABLE"]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    ml_status: Literal["AVAILABLE", "UNAVAILABLE"] = "AVAILABLE"
    ml_status_reason: Optional[Literal["PH_NOT_MEASURED", "MODEL_UNAVAILABLE", "INFERENCE_FAILED", "SENSOR_FAULT"]] = None
    success: bool = True

    model_config = ConfigDict(from_attributes=True)
