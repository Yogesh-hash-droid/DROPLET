from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class SystemConfigBase(BaseModel):
    # Legacy four-parameter thresholds (values preserved; nullable in the model so
    # historical configuration rows stay valid under the two-sensor scope).
    ph_min: Optional[float] = Field(None, ge=0.0, le=14.0, description="Minimum acceptable pH threshold (legacy; null = not configured)")
    ph_max: Optional[float] = Field(None, ge=0.0, le=14.0, description="Maximum acceptable pH threshold (legacy; null = not configured)")
    tds_max: float = Field(..., ge=0.0, description="Maximum acceptable TDS in ppm")
    turbidity_max: float = Field(..., ge=0.0, description="Maximum acceptable turbidity in NTU")
    temperature_min: Optional[float] = Field(None, description="Minimum water temperature in °C (legacy; null = not configured)")
    temperature_max: Optional[float] = Field(None, description="Maximum water temperature in °C (legacy; null = not configured)")
    # Phase 10 decision R-2 = B1 (FINAL): database-backed screening score bands.
    # GOOD: score >= status_good_min (default 70.0); POOR: score < status_poor_max (default 40.0);
    # MODERATE in between; UNAVAILABLE never maps to a scored band.
    status_good_min: float = Field(70.0, ge=0.0, le=100.0, description="Screening band: GOOD if score >= this value")
    status_poor_max: float = Field(40.0, ge=0.0, le=100.0, description="Screening band: POOR if score < this value")


class SystemConfigUpdate(BaseModel):
    ph_min: float | None = Field(None, ge=0.0, le=14.0)
    ph_max: float | None = Field(None, ge=0.0, le=14.0)
    tds_max: float | None = Field(None, ge=0.0)
    turbidity_max: float | None = Field(None, ge=0.0)
    temperature_min: float | None = None
    temperature_max: float | None = None
    # Band fields are validated by config_service so that BOTH range (0-100) and
    # ordering (status_poor_max < status_good_min) violations return HTTP 400
    # per plan section 3.5 (schema-level constraints would return 422 instead).
    status_good_min: float | None = Field(None, description="Screening band: GOOD if score >= this value (0-100)")
    status_poor_max: float | None = Field(None, description="Screening band: POOR if score < this value (0-100)")


class SystemConfigResponse(SystemConfigBase):
    id: int
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
