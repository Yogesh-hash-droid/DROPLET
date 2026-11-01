"""
Reusable sensor generator for the water quality simulator (Phase 6).

Every channel behaves like a slowly moving physical sensor:
  * a baseline the water tends to return to (mean reversion),
  * small gaussian noise on top of it,
  * a hard per-tick delta limit so values move *gradually*
    (no 7.1 -> 12.9 -> 3.2 jumps unless a scenario explicitly models a fault),
  * clamping inside physically valid ranges.

A scenario only supplies *targets*; this module owns the movement model.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, Mapping, Optional, Tuple

SENSOR_NAMES: Tuple[str, ...] = ("ph", "tds", "turbidity", "temperature")

# Physical bounds (also satisfy the API schema: ph 0-14, tds >= 0,
# turbidity >= 0, temperature -10..100 °C).
PHYSICAL_BOUNDS: Dict[str, Tuple[float, float]] = {
    "ph": (0.0, 14.0),
    "tds": (0.0, 100000.0),
    "turbidity": (0.0, 1000.0),
    "temperature": (-10.0, 100.0),
}

# Rounding used when a reading is emitted (matches API precision).
ROUNDING: Dict[str, int] = {"ph": 2, "tds": 1, "turbidity": 2, "temperature": 1}

# Per-channel movement model (alpha = reversion speed, sigma = noise,
# max_step = largest change allowed in a single tick = "gradual").
CHANNEL_PARAMS: Dict[str, Dict[str, float]] = {
    "ph": {"alpha": 0.10, "sigma": 0.03, "max_step": 0.12},
    "tds": {"alpha": 0.10, "sigma": 6.0, "max_step": 45.0},
    "turbidity": {"alpha": 0.10, "sigma": 0.08, "max_step": 0.70},
    "temperature": {"alpha": 0.08, "sigma": 0.12, "max_step": 1.50},
}


@dataclass
class SensorChannel:
    """One simulated sensor value that drifts towards a moving target."""

    name: str
    value: float
    alpha: float
    sigma: float
    max_step: float
    bounds: Tuple[float, float]

    def step(self, target: float, rng: random.Random, kick: float = 0.0) -> float:
        """
        Advance one tick: mean-revert toward `target`, add noise, apply an
        optional instantaneous `kick` (occasional event), then clamp the
        per-tick delta to `max_step` and the value to physical bounds.
        """
        desired = self.value + (target - self.value) * self.alpha
        desired += rng.gauss(0.0, self.sigma) + kick
        delta = desired - self.value
        if delta > self.max_step:
            delta = self.max_step
        elif delta < -self.max_step:
            delta = -self.max_step
        low, high = self.bounds
        self.value = min(high, max(low, self.value + delta))
        return self.value

    @property
    def rounded(self) -> float:
        return round(self.value, ROUNDING[self.name])


@dataclass(frozen=True)
class Reading:
    """One simulated telemetry sample (already rounded for the wire)."""

    step: int
    ph: float
    tds: float
    turbidity: float
    temperature: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "ph": self.ph,
            "tds": self.tds,
            "turbidity": self.turbidity,
            "temperature": self.temperature,
        }


# Callable producing the current target value of one channel at a given step.
TargetFn = Callable[[int], float]


@dataclass
class SensorGenerator:
    """
    Generates a sequence of realistic readings for one scenario.

    Reproducible: pass the same `seed` and scenario and you get the exact
    same sequence of values (used by the tests).
    """

    targets: Mapping[str, TargetFn]
    start: Mapping[str, float]
    seed: Optional[int] = None
    occasional_events: bool = False
    event_probability: float = 0.05
    rng: random.Random = field(init=False)
    channels: Dict[str, SensorChannel] = field(init=False, default_factory=dict)
    step_index: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        for name in SENSOR_NAMES:
            params = CHANNEL_PARAMS[name]
            self.channels[name] = SensorChannel(
                name=name,
                value=float(self.start[name]),
                alpha=params["alpha"],
                sigma=params["sigma"],
                max_step=params["max_step"],
                bounds=PHYSICAL_BOUNDS[name],
            )

    def _event_kick(self, name: str) -> float:
        """Occasional, small, self-recovering disturbance (mean reversion heals it)."""
        if not self.occasional_events:
            return 0.0
        if self.rng.random() > self.event_probability:
            return 0.0
        if name == "tds":
            return self.rng.uniform(20.0, 60.0)
        if name == "turbidity":
            return self.rng.uniform(0.3, 0.8)
        if name == "ph":
            return self.rng.choice([-1.0, 1.0]) * self.rng.uniform(0.10, 0.30)
        if name == "temperature":
            return self.rng.uniform(1.0, 2.5)
        return 0.0

    def next_reading(self) -> Reading:
        """Advance every channel by one tick and return the rounded sample."""
        step = self.step_index
        values: Dict[str, float] = {}
        for name in SENSOR_NAMES:
            channel = self.channels[name]
            target = float(self.targets[name](step))
            values[name] = channel.step(target, self.rng, self._event_kick(name))
        self.step_index += 1
        return Reading(
            step=step,
            ph=round(values["ph"], ROUNDING["ph"]),
            tds=round(values["tds"], ROUNDING["tds"]),
            turbidity=round(values["turbidity"], ROUNDING["turbidity"]),
            temperature=round(values["temperature"], ROUNDING["temperature"]),
        )

    def history(self, ticks: int) -> list:
        """Generate `ticks` readings in a row (used for tests/inspection)."""
        return [self.next_reading() for _ in range(ticks)]
