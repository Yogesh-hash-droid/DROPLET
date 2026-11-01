"""
Phase 4E - Run inference with the saved model.

Usage:
    python ml/predict.py --ph 7.2 --tds 250 --turbidity 1.5
    python ml/predict.py --json "{\"ph\": 7.2, \"tds\": 250, \"turbidity\": 1.5}"

Output: POTABLE / NOT POTABLE plus a confidence in [0, 1].
The prediction is a prototype classification only - it does not certify that
water is safe to drink.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import pipeline  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict water potability from sensor values.")
    parser.add_argument("--ph", type=float, help="pH value (0-14)")
    parser.add_argument("--tds", type=float, help="Total Dissolved Solids in ppm")
    parser.add_argument("--turbidity", type=float, help="Turbidity in NTU")
    parser.add_argument("--json", type=str, help='JSON record, e.g. {"ph":7.2,"tds":250,"turbidity":1.5}')
    parser.add_argument(
        "--artifact",
        type=str,
        default=str(pipeline.MODEL_PATH),
        help="Path to a model artifact (default: ml/models/water_potability_model.joblib)",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.json:
        try:
            record = json.loads(args.json)
        except json.JSONDecodeError as exc:
            print(f"ERROR: invalid --json payload: {exc}", file=sys.stderr)
            return 2
    else:
        if args.ph is None or args.tds is None or args.turbidity is None:
            print(
                "ERROR: provide either --json or all of --ph, --tds, --turbidity",
                file=sys.stderr,
            )
            return 2
        record = {"ph": args.ph, "tds": args.tds, "turbidity": args.turbidity}

    try:
        payload = pipeline.load_artifacts(Path(args.artifact))
        result = pipeline.predict_record(payload, record)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output = {
        "prediction": result["prediction"],
        "confidence": result["confidence"],
        "probabilities": result["probabilities"],
        "features": result["features"],
        "model": "RandomForest water potability (Phase 4 prototype)",
        "temperature_used": payload.get("temperature_used", False),
        "disclaimer": (
            "Prototype classification based on a public dataset; "
            "not a guarantee of drinking-water safety."
        ),
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
