"""Generate deterministic local telemetry records for demo/integration runs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def generate_records(entity_id: str, count: int) -> list[dict]:
    start = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    return [
        {
            "entity_id": entity_id,
            "timestamp": (start + timedelta(minutes=index)).isoformat(),
            "op_id": "baseline-traffic",
            "region": "us-east-1",
            "cloud_provider": "AWS",
            "numeric_features": [float(index + 1)],
            "categorical_fields": {
                "cloud": "AWS",
                "entity_type": "Instances",
                "namespace": "AWS/EC2",
                "metric_name": "CPUUtilization",
            },
        }
        for index in range(count)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity-id", default="demo-entity")
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--output", type=Path, default=Path("demo-data.json"))
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("--count must be positive")
    args.output.write_text(
        json.dumps(generate_records(args.entity_id, args.count), indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {args.count} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
