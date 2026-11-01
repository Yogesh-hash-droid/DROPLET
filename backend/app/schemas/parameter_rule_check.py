"""
Phase 10 - Parameter Rule Check response schemas.

The Parameter Rule Check is the PRIMARY assessment output for new two-sensor
records (decision P1: SEPARATE). Its vocabulary is PASS / WARNING / FAIL /
UNAVAILABLE and it never certifies drinking-water safety.
"""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# Exact contract strings from docs/PHASE_10_BACKEND_IMPLEMENTATION_PLAN.md section 3.2.
PARAMETER_RULE_CHECK_LABEL = "Parameter Rule Check"
PARAMETER_RULE_CHECK_SCOPE = "TDS and turbidity only"
PARAMETER_RULE_CHECK_DISCLAIMER = (
    "Passing this two-parameter check does NOT certify the water as potable "
    "or safe to drink. Laboratory testing is required."
)


class ParameterRuleCheckParameter(BaseModel):
    """Per-parameter rule outcome for one measured sensor value."""

    value: Optional[float] = None
    unit: Literal["ppm", "NTU"]
    status: Literal["PASS", "WARNING", "FAIL", "UNAVAILABLE"]
    detail: Optional[str] = None


class ParameterRuleCheckInfo(BaseModel):
    """Primary assessment block returned for new records (always present for
    score_method = TWO_PARAM_SCREENING rows; explicit null for historical rows)."""

    label: Literal["Parameter Rule Check"] = "Parameter Rule Check"
    status: Literal["PASS", "WARNING", "FAIL", "UNAVAILABLE"]
    parameters: Dict[str, ParameterRuleCheckParameter]
    unavailable_parameters: List[str] = Field(default_factory=list)
    scope: str = "TDS and turbidity only"
    disclaimer: str = PARAMETER_RULE_CHECK_DISCLAIMER
