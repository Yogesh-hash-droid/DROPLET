"""
Safety Rule Engine for Smart Water Quality Monitoring.

DISCLAIMER:
This system provides a project-specific prototype assessment based on configured
sensor thresholds. It does not replace certified laboratory water-quality testing
and must not be interpreted as a guarantee that water is safe for human consumption.
"""

import math
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from app.models.prediction import SafetyStatus
from app.models.system_config import SystemConfig


@dataclass
class ParameterEvaluation:
    name: str
    value: float
    status: SafetyStatus
    detail: Optional[str] = None


@dataclass
class SafetyEvaluationResult:
    status: SafetyStatus
    warning_message: Optional[str]
    violated_parameters: List[str] = field(default_factory=list)
    parameter_evaluations: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def evaluate_safety(
    ph: float,
    tds: float,
    turbidity: float,
    temperature: float,
    config: SystemConfig
) -> SafetyEvaluationResult:
    """
    Evaluates water quality telemetry deterministically against configured threshold boundaries.
    
    Status Hierarchy:
    - UNSAFE: At least one parameter is in a severe/dangerous range.
    - WARNING: No severe violations, but at least one parameter is moderately outside the preferred range.
    - SAFE: All parameters reside comfortably within configured operational limits.
    """
    evaluations: List[ParameterEvaluation] = []

    # 1. pH Evaluation
    # Preferred: [ph_min, ph_max]
    # Moderate Warning: [ph_min - 0.5, ph_min) or (ph_max, ph_max + 0.5]
    # Severe Unsafe: < ph_min - 0.5 or > ph_max + 0.5
    if ph < (config.ph_min - 0.5):
        evaluations.append(ParameterEvaluation(
            name="pH",
            value=ph,
            status=SafetyStatus.UNSAFE,
            detail=f"pH ({ph:.2f}) is severely acidic (threshold min: {config.ph_min:.2f})"
        ))
    elif ph < config.ph_min:
        evaluations.append(ParameterEvaluation(
            name="pH",
            value=ph,
            status=SafetyStatus.WARNING,
            detail=f"pH ({ph:.2f}) is moderately below configured minimum ({config.ph_min:.2f})"
        ))
    elif ph > (config.ph_max + 0.5):
        evaluations.append(ParameterEvaluation(
            name="pH",
            value=ph,
            status=SafetyStatus.UNSAFE,
            detail=f"pH ({ph:.2f}) is severely alkaline (threshold max: {config.ph_max:.2f})"
        ))
    elif ph > config.ph_max:
        evaluations.append(ParameterEvaluation(
            name="pH",
            value=ph,
            status=SafetyStatus.WARNING,
            detail=f"pH ({ph:.2f}) is moderately above configured maximum ({config.ph_max:.2f})"
        ))
    else:
        evaluations.append(ParameterEvaluation(
            name="pH",
            value=ph,
            status=SafetyStatus.SAFE
        ))

    # 2. TDS Evaluation (ppm)
    # Preferred: <= tds_max
    # Moderate Warning: (tds_max, tds_max * 1.5]
    # Severe Unsafe: > tds_max * 1.5
    tds_warn_threshold = config.tds_max * 1.5
    if tds > tds_warn_threshold:
        evaluations.append(ParameterEvaluation(
            name="TDS",
            value=tds,
            status=SafetyStatus.UNSAFE,
            detail=f"TDS ({tds:.1f} ppm) severely exceeds acceptable threshold ({config.tds_max:.1f} ppm)"
        ))
    elif tds > config.tds_max:
        evaluations.append(ParameterEvaluation(
            name="TDS",
            value=tds,
            status=SafetyStatus.WARNING,
            detail=f"TDS ({tds:.1f} ppm) is moderately above preferred threshold ({config.tds_max:.1f} ppm)"
        ))
    else:
        evaluations.append(ParameterEvaluation(
            name="TDS",
            value=tds,
            status=SafetyStatus.SAFE
        ))

    # 3. Turbidity Evaluation (NTU)
    # Preferred: <= turbidity_max
    # Moderate Warning: (turbidity_max, turbidity_max * 2.0]
    # Severe Unsafe: > turbidity_max * 2.0
    turb_warn_threshold = config.turbidity_max * 2.0
    if turbidity > turb_warn_threshold:
        evaluations.append(ParameterEvaluation(
            name="Turbidity",
            value=turbidity,
            status=SafetyStatus.UNSAFE,
            detail=f"Turbidity ({turbidity:.2f} NTU) severely exceeds clarity threshold ({config.turbidity_max:.2f} NTU)"
        ))
    elif turbidity > config.turbidity_max:
        evaluations.append(ParameterEvaluation(
            name="Turbidity",
            value=turbidity,
            status=SafetyStatus.WARNING,
            detail=f"Turbidity ({turbidity:.2f} NTU) is moderately above clarity threshold ({config.turbidity_max:.2f} NTU)"
        ))
    else:
        evaluations.append(ParameterEvaluation(
            name="Turbidity",
            value=turbidity,
            status=SafetyStatus.SAFE
        ))

    # 4. Temperature Evaluation (°C)
    # Preferred: [temperature_min, temperature_max]
    # Moderate Warning: [temperature_min - 5.0, temperature_min) or (temperature_max, temperature_max + 5.0]
    # Severe Unsafe: < temperature_min - 5.0 or > temperature_max + 5.0
    if temperature < (config.temperature_min - 5.0) or temperature > (config.temperature_max + 5.0):
        evaluations.append(ParameterEvaluation(
            name="Temperature",
            value=temperature,
            status=SafetyStatus.UNSAFE,
            detail=f"Temperature ({temperature:.1f} °C) is severely outside safe range [{config.temperature_min:.1f} - {config.temperature_max:.1f} °C]"
        ))
    elif temperature < config.temperature_min or temperature > config.temperature_max:
        evaluations.append(ParameterEvaluation(
            name="Temperature",
            value=temperature,
            status=SafetyStatus.WARNING,
            detail=f"Temperature ({temperature:.1f} °C) is slightly outside preferred range [{config.temperature_min:.1f} - {config.temperature_max:.1f} °C]"
        ))
    else:
        evaluations.append(ParameterEvaluation(
            name="Temperature",
            value=temperature,
            status=SafetyStatus.SAFE
        ))

    # Aggregate overall status and generate warning explanation
    has_unsafe = any(e.status == SafetyStatus.UNSAFE for e in evaluations)
    has_warning = any(e.status == SafetyStatus.WARNING for e in evaluations)

    if has_unsafe:
        overall_status = SafetyStatus.UNSAFE
    elif has_warning:
        overall_status = SafetyStatus.WARNING
    else:
        overall_status = SafetyStatus.SAFE

    violated_params: List[str] = []
    violation_details: List[str] = []
    param_dict: Dict[str, Dict[str, Any]] = {}

    for e in evaluations:
        param_dict[e.name.lower()] = {
            "value": e.value,
            "status": e.status.value,
            "detail": e.detail
        }
        if e.status != SafetyStatus.SAFE:
            violated_params.append(e.name)
            if e.detail:
                violation_details.append(e.detail)

    warning_message: Optional[str] = None
    if violation_details:
        warning_message = " | ".join(violation_details)

    return SafetyEvaluationResult(
        status=overall_status,
        warning_message=warning_message,
        violated_parameters=violated_params,
        parameter_evaluations=param_dict
    )


# --------------------------------------------------------------------------------
# Phase 10 — Parameter Rule Check (TDS + turbidity only).
# PRIMARY assessment vocabulary for new records: PASS | WARNING | FAIL | UNAVAILABLE.
# Overall aggregation: FAIL > WARNING > UNAVAILABLE > PASS - problem evidence is
# never masked by missing data, and an incomplete check can never read PASS.
# The legacy evaluate_safety() above stays untouched for historical records.
# --------------------------------------------------------------------------------


@dataclass
class ParameterRuleResult:
    name: str                    # "tds" | "turbidity"
    value: Optional[float]
    unit: str                    # "ppm" | "NTU"
    status: str                  # PASS | WARNING | FAIL | UNAVAILABLE
    detail: Optional[str]


@dataclass
class ParameterRuleCheckResult:
    status: str                            # overall: PASS | WARNING | FAIL | UNAVAILABLE
    parameters: List[ParameterRuleResult]
    unavailable_parameters: List[str]
    warning_message: Optional[str]         # joined details (persisted, as today)
    storage_status: SafetyStatus           # new rows only: persistence mirror (P1)


_STATUS_RANK = {"PASS": 0, "UNAVAILABLE": 1, "WARNING": 2, "FAIL": 3}

# P1: storage mirror for the NOT NULL predictions.safety_status column only.
# API consumers read `parameter_rule_check`; SAFE/UNSAFE are never used as
# new-record display labels. Overall-UNAVAILABLE -> WARNING is defensive-only.
_STORAGE_MIRROR = {
    "PASS": SafetyStatus.SAFE,
    "WARNING": SafetyStatus.WARNING,
    "FAIL": SafetyStatus.UNSAFE,
    "UNAVAILABLE": SafetyStatus.WARNING,
}


def _rule_value_is_valid(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def evaluate_parameter_rule_check(
    tds: Optional[float],
    turbidity: Optional[float],
    config: SystemConfig
) -> ParameterRuleCheckResult:
    """
    Two-parameter rule check against the existing configured thresholds
    (bands unchanged: TDS PASS <= tds_max, WARNING <= tds_max * 1.5, else FAIL;
    turbidity PASS <= turbidity_max, WARNING <= turbidity_max * 2.0, else FAIL).

    Missing/invalid values -> that parameter is UNAVAILABLE with detail
    "not measured" - NEVER PASS. This check applies only to new records
    (score_method = TWO_PARAM_SCREENING); historical rows are never evaluated.
    """
    parameters: List[ParameterRuleResult] = []
    unavailable_parameters: List[str] = []

    # 1. TDS (ppm)
    if not _rule_value_is_valid(tds):
        unavailable_parameters.append("tds")
        parameters.append(ParameterRuleResult(
            name="tds", value=None, unit="ppm", status="UNAVAILABLE", detail="not measured"
        ))
    elif float(tds) > config.tds_max * 1.5:
        parameters.append(ParameterRuleResult(
            name="tds", value=float(tds), unit="ppm", status="FAIL",
            detail=f"TDS ({float(tds):.1f} ppm) severely exceeds acceptable threshold ({config.tds_max:.1f} ppm)"
        ))
    elif float(tds) > config.tds_max:
        parameters.append(ParameterRuleResult(
            name="tds", value=float(tds), unit="ppm", status="WARNING",
            detail=f"TDS ({float(tds):.1f} ppm) is moderately above preferred threshold ({config.tds_max:.1f} ppm)"
        ))
    else:
        parameters.append(ParameterRuleResult(
            name="tds", value=float(tds), unit="ppm", status="PASS", detail=None
        ))

    # 2. Turbidity (NTU)
    if not _rule_value_is_valid(turbidity):
        unavailable_parameters.append("turbidity")
        parameters.append(ParameterRuleResult(
            name="turbidity", value=None, unit="NTU", status="UNAVAILABLE", detail="not measured"
        ))
    elif float(turbidity) > config.turbidity_max * 2.0:
        parameters.append(ParameterRuleResult(
            name="turbidity", value=float(turbidity), unit="NTU", status="FAIL",
            detail=f"Turbidity ({float(turbidity):.1f} NTU) severely exceeds clarity threshold ({config.turbidity_max:.1f} NTU)"
        ))
    elif float(turbidity) > config.turbidity_max:
        parameters.append(ParameterRuleResult(
            name="turbidity", value=float(turbidity), unit="NTU", status="WARNING",
            detail=f"Turbidity ({float(turbidity):.1f} NTU) is moderately above clarity threshold ({config.turbidity_max:.1f} NTU)"
        ))
    else:
        parameters.append(ParameterRuleResult(
            name="turbidity", value=float(turbidity), unit="NTU", status="PASS", detail=None
        ))

    # Overall aggregation: FAIL > WARNING > UNAVAILABLE > PASS
    overall = max((p.status for p in parameters), key=lambda s: _STATUS_RANK[s])

    # Joined details of every non-PASS parameter (same " | " join as legacy).
    details = [p.detail for p in parameters if p.status != "PASS" and p.detail]
    warning_message: Optional[str] = " | ".join(details) if details else None

    return ParameterRuleCheckResult(
        status=overall,
        parameters=parameters,
        unavailable_parameters=unavailable_parameters,
        warning_message=warning_message,
        storage_status=_STORAGE_MIRROR[overall],
    )
