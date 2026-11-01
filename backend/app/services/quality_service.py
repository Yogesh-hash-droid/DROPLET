"""
Water Quality Scoring Service.

DISCLAIMER:
This score is a project-specific composite quality metric (0–100) created for this
educational prototype system. It is NOT an official statutory Water Quality Index (WQI)
and does not certify biological, chemical, or radiological potability.

Phase 10: the module additionally provides the two-parameter screening score
(TDS + turbidity). It is a PRELIMINARY screening output only — neither GOOD nor
any other band certifies the water as safe to drink; laboratory testing is required.
The legacy four-parameter function above remains untouched for historical records.
"""

import math
from typing import Dict, Optional
from dataclasses import dataclass
from app.models.system_config import SystemConfig


@dataclass
class QualityScoreBreakdown:
    overall_score: float
    sub_scores: Dict[str, float]
    weights: Dict[str, float]


def calculate_water_quality_score(
    ph: float,
    tds: float,
    turbidity: float,
    temperature: float,
    config: SystemConfig
) -> QualityScoreBreakdown:
    """
    Calculates a transparent, deterministic composite water quality score bounded strictly within [0.0, 100.0].

    Weighting Distribution:
    - pH:          35% (0.35)
    - TDS:         30% (0.30)
    - Turbidity:   25% (0.25)
    - Temperature: 10% (0.10)

    Each parameter computes a sub-index S in [0.0, 100.0] normalized against configured acceptable limits.
    """
    # 1. pH Sub-index S_ph (Weight: 35%)
    # Ideal range: [config.ph_min, config.ph_max] (100 pts)
    # Below min: scales down towards 0 at pH 0
    # Above max: scales down towards 0 at pH 14
    if config.ph_min <= ph <= config.ph_max:
        s_ph = 100.0
    elif ph < config.ph_min:
        if config.ph_min > 0:
            s_ph = max(0.0, 100.0 * (ph / config.ph_min))
        else:
            s_ph = 0.0
    else:  # ph > config.ph_max
        if config.ph_max < 14.0:
            s_ph = max(0.0, 100.0 * ((14.0 - ph) / (14.0 - config.ph_max)))
        else:
            s_ph = 0.0
    s_ph = min(100.0, max(0.0, s_ph))

    # 2. TDS Sub-index S_tds (Weight: 30%)
    # <= 200 ppm: 100 pts (excellent)
    # 200 ppm to tds_max: drops from 100 to 80 pts
    # tds_max to 2000 ppm: drops from 80 to 0 pts
    # > 2000 ppm: 0 pts
    if tds <= 200.0:
        s_tds = 100.0
    elif tds <= config.tds_max:
        if config.tds_max > 200.0:
            ratio = (tds - 200.0) / (config.tds_max - 200.0)
            s_tds = 100.0 - (20.0 * ratio)
        else:
            s_tds = 80.0
    else:  # tds > config.tds_max
        severe_tds_limit = max(config.tds_max + 100.0, 2000.0)
        ratio = (tds - config.tds_max) / (severe_tds_limit - config.tds_max)
        s_tds = max(0.0, 80.0 * (1.0 - ratio))
    s_tds = min(100.0, max(0.0, s_tds))

    # 3. Turbidity Sub-index S_turb (Weight: 25%)
    # <= 1.0 NTU: 100 pts (crystal clear)
    # 1.0 to turbidity_max: drops from 100 to 75 pts
    # turbidity_max to 50 NTU: drops from 75 to 0 pts
    # > 50 NTU: 0 pts
    if turbidity <= 1.0:
        s_turb = 100.0
    elif turbidity <= config.turbidity_max:
        if config.turbidity_max > 1.0:
            ratio = (turbidity - 1.0) / (config.turbidity_max - 1.0)
            s_turb = 100.0 - (25.0 * ratio)
        else:
            s_turb = 75.0
    else:  # turbidity > config.turbidity_max
        severe_turb_limit = max(config.turbidity_max + 5.0, 50.0)
        ratio = (turbidity - config.turbidity_max) / (severe_turb_limit - config.turbidity_max)
        s_turb = max(0.0, 75.0 * (1.0 - ratio))
    s_turb = min(100.0, max(0.0, s_turb))

    # 4. Temperature Sub-index S_temp (Weight: 10%)
    # [temperature_min, temperature_max]: 100 pts
    # Below min: drops towards 0 at 0 °C
    # Above max: drops towards 0 at 60 °C
    if config.temperature_min <= temperature <= config.temperature_max:
        s_temp = 100.0
    elif temperature < config.temperature_min:
        if config.temperature_min > 0.0:
            s_temp = max(0.0, 100.0 * (temperature / config.temperature_min))
        else:
            s_temp = 0.0
    else:  # temperature > config.temperature_max
        if config.temperature_max < 60.0:
            s_temp = max(0.0, 100.0 * ((60.0 - temperature) / (60.0 - config.temperature_max)))
        else:
            s_temp = 0.0
    s_temp = min(100.0, max(0.0, s_temp))

    # Calculate weighted aggregate composite score
    w_ph = 0.35
    w_tds = 0.30
    w_turb = 0.25
    w_temp = 0.10

    composite = (s_ph * w_ph) + (s_tds * w_tds) + (s_turb * w_turb) + (s_temp * w_temp)
    clamped_score = round(min(100.0, max(0.0, composite)), 1)

    return QualityScoreBreakdown(
        overall_score=clamped_score,
        sub_scores={
            "ph": round(s_ph, 1),
            "tds": round(s_tds, 1),
            "turbidity": round(s_turb, 1),
            "temperature": round(s_temp, 1)
        },
        weights={
            "ph": w_ph,
            "tds": w_tds,
            "turbidity": w_turb,
            "temperature": w_temp
        }
    )


# --------------------------------------------------------------------------------
# Phase 10 — two-parameter screening score (TDS + turbidity only).
# Formula (final decision, plan section 4):
#   quality_score = round((S_tds * 0.55) + (S_turbidity * 0.45), 1), clamped [0, 100]
# Only the FINAL score is rounded; intermediate sub-indices keep full precision.
# The sub-index curves are copied verbatim from the TDS/turbidity blocks above so
# the historical four-parameter function is never touched.
# --------------------------------------------------------------------------------

WEIGHT_TDS = 0.55
WEIGHT_TURBIDITY = 0.45

# Authoritative per-band explanation texts (docs/PHASE_9_QUALITY_ASSESSMENT_DESIGN.md).
# None of them describes any band as safe to drink or certified.
SCREENING_EXPLANATIONS = {
    "GOOD": "Preliminary screening score for TDS and turbidity is within the configured acceptable range.",
    "MODERATE": "Preliminary screening score is partly outside the preferred range — review thresholds and inspect the supply.",
    "POOR": "Preliminary screening score is well outside the acceptable range for TDS and turbidity.",
    "UNAVAILABLE": "Screening score unavailable — a required sensor reading is missing or invalid.",
}


@dataclass
class ScreeningScoreResult:
    # None -> screening_status UNAVAILABLE (no partial score is ever produced).
    overall_score: Optional[float]
    sub_scores: Dict[str, float]            # "tds", "turbidity" (rounded for display, 4 dp)
    weights: Dict[str, float]               # {"tds": 0.55, "turbidity": 0.45}
    screening_status: str                   # GOOD | MODERATE | POOR | UNAVAILABLE
    screening_explanation: Optional[str]
    unavailable_reason: Optional[str]       # e.g. "TDS_NOT_MEASURED"


def classify_screening_status(score: Optional[float], config: SystemConfig) -> str:
    """
    B1 (database-backed bands):
      UNAVAILABLE  score is None
      GOOD         score >= config.status_good_min (default 70.0)
      MODERATE     config.status_poor_max <= score < config.status_good_min (default >= 40.0)
      POOR         score < config.status_poor_max (default 40.0)
    """
    if score is None:
        return "UNAVAILABLE"
    if score >= config.status_good_min:
        return "GOOD"
    if score >= config.status_poor_max:
        return "MODERATE"
    return "POOR"


def _is_valid_measurement(value) -> bool:
    """A usable measurement is a finite real number (booleans are never valid)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _tds_sub_index(tds: float, config: SystemConfig) -> float:
    # Copied verbatim from calculate_water_quality_score (TDS block).
    if tds <= 200.0:
        s_tds = 100.0
    elif tds <= config.tds_max:
        if config.tds_max > 200.0:
            ratio = (tds - 200.0) / (config.tds_max - 200.0)
            s_tds = 100.0 - (20.0 * ratio)
        else:
            s_tds = 80.0
    else:  # tds > config.tds_max
        severe_tds_limit = max(config.tds_max + 100.0, 2000.0)
        ratio = (tds - config.tds_max) / (severe_tds_limit - config.tds_max)
        s_tds = max(0.0, 80.0 * (1.0 - ratio))
    return min(100.0, max(0.0, s_tds))


def _turbidity_sub_index(turbidity: float, config: SystemConfig) -> float:
    # Copied verbatim from calculate_water_quality_score (turbidity block).
    if turbidity <= 1.0:
        s_turb = 100.0
    elif turbidity <= config.turbidity_max:
        if config.turbidity_max > 1.0:
            ratio = (turbidity - 1.0) / (config.turbidity_max - 1.0)
            s_turb = 100.0 - (25.0 * ratio)
        else:
            s_turb = 75.0
    else:  # turbidity > config.turbidity_max
        severe_turb_limit = max(config.turbidity_max + 5.0, 50.0)
        ratio = (turbidity - config.turbidity_max) / (severe_turb_limit - config.turbidity_max)
        s_turb = max(0.0, 75.0 * (1.0 - ratio))
    return min(100.0, max(0.0, s_turb))


def calculate_screening_score(
    tds: Optional[float],
    turbidity: Optional[float],
    config: SystemConfig
) -> ScreeningScoreResult:
    """
    Two-parameter (TDS + turbidity) preliminary screening score, 0-100.

    - Weights: TDS 0.55, turbidity 0.45 (sum = 1.00).
    - Required inputs missing/invalid -> overall_score None, status UNAVAILABLE,
      unavailable_reason set; NO partial score and NO defaulting/fabrication.
    - Bands come from config.status_good_min / config.status_poor_max (B1).
    - PRELIMINARY SCREENING ONLY: no band certifies the water as safe to drink;
      laboratory testing is required.
    """
    weights = {"tds": WEIGHT_TDS, "turbidity": WEIGHT_TURBIDITY}

    tds_valid = _is_valid_measurement(tds)
    turbidity_valid = _is_valid_measurement(turbidity)

    if not tds_valid or not turbidity_valid:
        if not tds_valid:
            reason = "TDS_NOT_MEASURED" if tds is None else "TDS_INVALID"
        else:
            reason = "TURBIDITY_NOT_MEASURED" if turbidity is None else "TURBIDITY_INVALID"
        return ScreeningScoreResult(
            overall_score=None,
            sub_scores={},  # no partial score is ever produced
            weights=weights,
            screening_status="UNAVAILABLE",
            screening_explanation=SCREENING_EXPLANATIONS["UNAVAILABLE"],
            unavailable_reason=reason,
        )

    # Intermediate sub-indices at full precision...
    s_tds = _tds_sub_index(float(tds), config)
    s_turb = _turbidity_sub_index(float(turbidity), config)

    composite = (s_tds * WEIGHT_TDS) + (s_turb * WEIGHT_TURBIDITY)
    # ...only the final score is clamped and rounded (1 decimal).
    final_score = round(min(100.0, max(0.0, composite)), 1)

    status = classify_screening_status(final_score, config)

    return ScreeningScoreResult(
        overall_score=final_score,
        sub_scores={"tds": round(s_tds, 4), "turbidity": round(s_turb, 4)},
        weights=weights,
        screening_status=status,
        screening_explanation=SCREENING_EXPLANATIONS[status],
        unavailable_reason=None,
    )
