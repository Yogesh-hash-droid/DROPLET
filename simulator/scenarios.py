"""
Selectable simulator scenarios (Phase 6).

Each scenario documents what water condition it represents and how the four
sensor targets move over time. Targets are *goals*, not instant values: the
sensor model in `sensors.py` always moves gradually towards them and mean-
reverts when a scenario ends in a healthy state.

Safety thresholds used when documenting expected behaviour (default config):
    pH      WARNING < 6.5 or > 8.5   UNSAFE < 6.0 or > 9.0
    TDS     WARNING > 500 ppm        UNSAFE > 750 ppm
    Turb.   WARNING > 5 NTU          UNSAFE > 10 NTU
    Temp.   WARNING < 10 or > 35 °C  UNSAFE < 5 or > 40 °C
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Tuple

from simulator.sensors import SENSOR_NAMES, TargetFn

# Healthy domestic tap-water baseline used by most scenarios.
BASELINE: Dict[str, float] = {
    "ph": 7.1,
    "tds": 215.0,
    "turbidity": 1.4,
    "temperature": 26.5,
}

# Deliberately unhealthy starting point for the recovery scenario.
DEGRADED: Dict[str, float] = {
    "ph": 5.2,
    "tds": 850.0,
    "turbidity": 9.5,
    "temperature": 38.0,
}


def _ramp(start: float, end: float, steps: int) -> TargetFn:
    """Linear target movement from `start` to `end` over `steps` ticks."""
    if steps <= 0:
        return lambda _step: end
    span = end - start

    def target(step: int) -> float:
        progress = min(1.0, max(0.0, step / float(steps)))
        return start + span * progress

    return target


def _hold(value: float) -> TargetFn:
    return lambda _step: value


def _temperature_spike(step: int) -> float:
    """
    Rise 26.5 -> 46 °C (UNSAFE > 40), hold while the sensor catches up, then
    decay back to baseline - a classic thermal event with recovery.
    """
    if step <= 14:
        return _ramp(26.5, 46.0, 14)(step)
    if step <= 30:
        return 46.0
    if step <= 54:
        return _ramp(46.0, 26.5, 24)(step - 30)
    return 26.5


@dataclass(frozen=True)
class Scenario:
    key: str
    aliases: Tuple[str, ...]
    description: str
    start: Dict[str, float]
    targets: Dict[str, TargetFn]
    occasional_events: bool = False

    @property
    def target_at(self) -> Dict[str, float]:
        """Targets at step 0 (mostly informational/tests)."""
        return {name: float(self.targets[name](0)) for name in SENSOR_NAMES}

    def build_generator(self, seed=None):
        from simulator.sensors import SensorGenerator

        return SensorGenerator(
            targets=self.targets,
            start=self.start,
            seed=seed,
            occasional_events=self.occasional_events,
        )


def _scenario(
    key: str,
    aliases: Tuple[str, ...],
    description: str,
    overrides: Dict[str, Tuple[float, float, int]],
    start: Dict[str, float] = None,
    events: bool = False,
) -> Scenario:
    """
    Build a Scenario from per-sensor (start_value, end_value, ramp_steps)
    overrides; sensors without an override simply hold the baseline.
    """
    base_start = dict(BASELINE) if start is None else dict(start)
    targets: Dict[str, TargetFn] = {}
    for name in SENSOR_NAMES:
        if name in overrides:
            from_start, to_end, steps = overrides[name]
            base_start.setdefault(name, from_start)
            targets[name] = _ramp(from_start, to_end, steps)
        else:
            targets[name] = _hold(base_start[name])
    return Scenario(
        key=key,
        aliases=aliases,
        description=description,
        start=base_start,
        targets=targets,
        occasional_events=events,
    )


SCENARIOS: Dict[str, Scenario] = {}


def _register(scenario: Scenario) -> Scenario:
    SCENARIOS[scenario.key] = scenario
    return scenario


# 1. NORMAL ---------------------------------------------------------------
_register(_scenario(
    "NORMAL",
    ("normal", "n"),
    "Healthy tap water. All four sensors hover around their baselines with "
    "small noise and occasional self-recovering disturbances (a brief TDS or "
    "turbidity bump that mean-reversion pulls back). Expected: SAFE, "
    "high Water Quality Score.",
    overrides={},
    events=True,
))

# 2. PH_DRIFT_LOW ---------------------------------------------------------
_register(_scenario(
    "PH_DRIFT_LOW",
    ("ph_drift_low", "drift_low", "low_ph"),
    "Slow acidification (e.g. CO2 uptake or weak acidic inflow): pH drifts "
    "from 7.1 down to 5.8 over ~25 ticks, crossing WARNING (<6.5) and then "
    "UNSAFE (<6.0). TDS/turbidity/temperature stay normal.",
    overrides={"ph": (7.1, 5.8, 25)},
))

# 3. PH_DRIFT_HIGH --------------------------------------------------------
_register(_scenario(
    "PH_DRIFT_HIGH",
    ("ph_drift_high", "drift_high", "high_ph"),
    "Slow alkalinization: pH drifts from 7.1 up to 9.6 over ~25 ticks, "
    "crossing WARNING (>8.5) and then UNSAFE (>9.0). Other sensors normal.",
    overrides={"ph": (7.1, 9.6, 25)},
))

# 4. HIGH_TDS -------------------------------------------------------------
_register(_scenario(
    "HIGH_TDS",
    ("high_tds", "tds"),
    "Dissolved-solids contamination (salinity/mineral ingress): TDS climbs "
    "from 230 to 900 ppm over ~20 ticks, crossing WARNING (>500) and then "
    "UNSAFE (>750). pH/turbidity/temperature normal.",
    overrides={"tds": (230.0, 900.0, 20)},
))

# 5. HIGH_TURBIDITY -------------------------------------------------------
_register(_scenario(
    "HIGH_TURBIDITY",
    ("high_turbidity", "high_turb", "turbidity"),
    "Suspended solids (stirred sediment, runoff): turbidity rises from 1.5 "
    "to 12 NTU over ~18 ticks, crossing WARNING (>5) and UNSAFE (>10). "
    "Other sensors normal.",
    overrides={"turbidity": (1.5, 12.0, 18)},
))

# 6. ACIDIC_WATER ---------------------------------------------------------
_register(_scenario(
    "ACIDIC_WATER",
    ("acidic", "acidic_water", "acid"),
    "Strongly acidic water (acid mine drainage / industrial spill): pH falls "
    "from 7.0 to 4.5 (~14 ticks, well below the 6.0 UNSAFE boundary) while "
    "TDS and turbidity rise slightly. Expected: UNSAFE with violated pH.",
    overrides={"ph": (7.0, 4.5, 14), "tds": (215.0, 320.0, 20), "turbidity": (1.4, 2.2, 20)},
))

# 7. ALKALINE_WATER -------------------------------------------------------
_register(_scenario(
    "ALKALINE_WATER",
    ("alkaline", "alkaline_water", "base"),
    "Strongly alkaline water (lye/cement contamination): pH rises from 7.4 "
    "to 10.2 (~14 ticks, above the 9.0 UNSAFE boundary). Other sensors "
    "normal. Expected: UNSAFE with violated pH.",
    overrides={"ph": (7.4, 10.2, 14)},
))

# 8. TEMPERATURE_SPIKE ----------------------------------------------------
_register(_scenario(
    "TEMPERATURE_SPIKE",
    ("temperature_spike", "temp_spike", "temperature"),
    "Thermal event (hot discharge / sensor placed near a heater): temperature "
    "rises 26.5 -> 46 °C in ~14 ticks, holds while the sensor catches up "
    "(WARNING >35, UNSAFE >40 are both crossed) and then decays back to "
    "baseline by ~tick 54 (recovery). pH/TDS/turbidity normal - temperature "
    "is NOT an ML feature, so the ML verdict may disagree with the safety "
    "verdict here.",
    overrides={},
))
SCENARIOS["TEMPERATURE_SPIKE"].targets["temperature"] = _temperature_spike

# 9. MULTIPLE_PROBLEM -----------------------------------------------------
_register(_scenario(
    "MULTIPLE_PROBLEM",
    ("multiple_problem", "multiple", "multi"),
    "Simultaneous contamination: pH drifts to 5.6, TDS to 850 ppm, "
    "turbidity to 11 NTU and temperature to 38 °C. Several rules fire at "
    "once; expected: UNSAFE with multiple violated parameters and a much "
    "lower Water Quality Score.",
    overrides={
        "ph": (7.0, 5.6, 20),
        "tds": (230.0, 850.0, 18),
        "turbidity": (1.5, 11.0, 18),
        "temperature": (26.5, 38.0, 15),
    },
))

# 10. SENSOR_RECOVERY -----------------------------------------------------
_register(_scenario(
    "SENSOR_RECOVERY",
    ("sensor_recovery", "recovery", "recover"),
    "Water starts degraded (pH 5.2, TDS 850, turbidity 9.5, 38 °C - several "
    "rules violated) and gradually recovers to healthy baselines over ~20 "
    "ticks. Demonstrates recovery: violations disappear and the score climbs.",
    start=DEGRADED,
    overrides={
        "ph": (DEGRADED["ph"], 7.0, 20),
        "tds": (DEGRADED["tds"], 220.0, 20),
        "turbidity": (DEGRADED["turbidity"], 1.5, 20),
        "temperature": (DEGRADED["temperature"], 27.0, 20),
    },
))


# ---------------------------------------------------------------------------
# Lookup helpers (CLI + tests)
# ---------------------------------------------------------------------------
ALIASES: Dict[str, str] = {}
for _scenario_obj in SCENARIOS.values():
    for _alias in _scenario_obj.aliases:
        ALIASES[_alias.lower()] = _scenario_obj.key
    ALIASES[_scenario_obj.key.lower()] = _scenario_obj.key

DEFAULT_SCENARIO = "NORMAL"


def resolve_scenario(name: str) -> Scenario:
    """Resolve a CLI/user supplied scenario name (case-insensitive)."""
    if name is None:
        raise KeyError("scenario name is required")
    key = ALIASES.get(str(name).strip().lower())
    if key is None:
        raise KeyError(
            f"unknown scenario {name!r}; choose from: {', '.join(sorted(SCENARIOS))}"
        )
    return SCENARIOS[key]
