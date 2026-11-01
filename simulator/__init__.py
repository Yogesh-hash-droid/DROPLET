"""Water quality telemetry simulator (Phase 6) - software-generated data only."""
from simulator.client import ApiResponse, build_payload, post_reading
from simulator.scenarios import ALIASES, BASELINE, SCENARIOS, Scenario, resolve_scenario
from simulator.sensors import Reading, SensorGenerator

__all__ = [
    "ALIASES",
    "ApiResponse",
    "BASELINE",
    "Reading",
    "SCENARIOS",
    "Scenario",
    "SensorGenerator",
    "build_payload",
    "post_reading",
    "resolve_scenario",
]
