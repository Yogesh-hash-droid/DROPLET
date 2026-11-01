#!/usr/bin/env python3
"""
Realistic multi-scenario water sensor simulator (Phase 6).

Generates pH / TDS / turbidity / temperature values the way a real sensor
node would (baseline + noise + gradual drift + events + recovery) and POSTs
them to the live backend at `POST /api/readings`, so safety rules, the Water
Quality Score and the ML inference all run through the real API.

`source` is always "SIMULATION" - this is software-generated data, NOT real
ESP32 hardware telemetry.

Usage:
    python simulator/simulator.py --scenario normal
    python simulator/simulator.py --scenario high_tds --interval 3 --count 20
    python simulator/simulator.py --scenario acidic --device-id SIMULATOR-002
    python simulator/simulator.py --scenario multiple_problem --seed 42 --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

# Allow running the file directly (`python simulator.py`) as a module import.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.client import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    ApiResponse,
    build_payload,
    post_reading,
)
from simulator.scenarios import ALIASES, SCENARIOS, resolve_scenario  # noqa: E402

HEADER = (
    f"{'STEP':>4}  {'TIME':19}  {'DEVICE':16}  {'SCENARIO':17}  "
    f"{'PH':>5}  {'TDS':>7}  {'TURB':>5}  {'TEMP':>5}  "
    f"{'HTTP':>4}  {'PREDICTION':11}  {'CONF':>6}  {'SAFETY':7}"
)


def format_row(
    step: int,
    timestamp: str,
    device_id: str,
    scenario_key: str,
    reading,
    response: Optional[ApiResponse],
) -> str:
    """One fixed-width result line (HTTP / prediction / confidence / safety)."""
    if response is None:  # --dry-run
        http, prediction, confidence, safety = "--", "-", "-", "-"
    else:
        http = str(response.status) if response.status is not None else "ERR"
        prediction = response.prediction or "-"
        confidence = f"{response.confidence:.3f}" if response.confidence is not None else "-"
        safety = response.safety_status or "-"
    return (
        f"{step:>4}  {timestamp:19}  {device_id:16}  {scenario_key:17}  "
        f"{reading.ph:>5.2f}  {reading.tds:>7.1f}  {reading.turbidity:>5.2f}  "
        f"{reading.temperature:>5.1f}  {http:>4}  {prediction:11}  "
        f"{confidence:>6}  {safety:7}"
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="simulator.py",
        description=(
            "Simulated ESP32-style water sensor node posting to POST /api/readings. "
            "SIMULATION data only - not real hardware."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--scenario",
        type=str.lower,
        default="normal",
        choices=sorted(ALIASES),
        help="scenario to run (e.g. normal, ph_drift_low, high_tds, acidic, "
        "alkaline, high_turbidity, temperature_spike, multiple_problem, recovery)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between readings",
    )
    parser.add_argument(
        "--device-id",
        type=str,
        default="SIMULATOR-001",
        help="device_id sent to the API",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="number of readings to send; omit for continuous operation (Ctrl+C)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="random seed for reproducible sequences",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=DEFAULT_BASE_URL,
        help="backend base URL",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="generate and print readings without calling the API",
    )

    args = parser.parse_args(argv)
    if args.interval < 0:
        parser.error("--interval must be >= 0")
    if args.count is not None and args.count < 1:
        parser.error("--count must be >= 1")
    if not args.device_id.strip():
        parser.error("--device-id must be non-empty")
    return args


def run(args: argparse.Namespace) -> int:
    scenario = resolve_scenario(args.scenario)
    generator = scenario.build_generator(seed=args.seed)
    total = args.count if args.count is not None else None
    ticks = range(total) if total is not None else iter(int, 1)  # infinite

    print(f"Scenario   : {scenario.key}")
    print(f"Details    : {scenario.description}")
    print(f"Device     : {args.device_id}  (source: SIMULATION - software data, not ESP32)")
    print(f"Target     : {'dry-run (no API calls)' if args.dry_run else args.base_url + '/api/readings'}")
    print(f"Interval   : {args.interval}s   Seed: {args.seed}")
    print(f"{'continuous - press Ctrl+C to stop' if total is None else f'{total} reading(s)'}")
    print(HEADER)

    failures = 0
    sent = 0
    try:
        for _ in ticks:
            reading = generator.next_reading()
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            response: Optional[ApiResponse] = None
            error_detail: Optional[str] = None
            if args.dry_run:
                response = None
            else:
                try:
                    payload = build_payload(args.device_id, reading)
                except ValueError as exc:
                    failures += 1
                    print(format_row(generator.step_index - 1, timestamp, args.device_id,
                                     scenario.key, reading, None))
                    print(f"     !! invalid payload: {exc}")
                    continue
                response = post_reading(args.base_url, payload, timeout=args.timeout)
                if not response.ok:
                    failures += 1
                    error_detail = response.detail
            sent += 1
            print(format_row(generator.step_index - 1, timestamp, args.device_id,
                             scenario.key, reading, response))
            if error_detail:
                print(f"     !! API error: {error_detail}")
            if args.interval > 0 and (total is None or sent < total):
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped by user (Ctrl+C).")
        return 0

    if failures:
        print(f"\nFinished with {sent} reading(s), {failures} API error(s).")
        return 1
    print(f"\nFinished: {sent} reading(s) sent successfully.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Never crash the terminal on a character it cannot encode (e.g. "°C").
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001 - reconfiguration is best-effort
            pass
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
