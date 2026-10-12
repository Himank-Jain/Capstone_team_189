"""Run the complete synthetic alert flow without cloud credentials."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from backend.api_demo_ext.app import app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="amazon")
    parser.add_argument("--scenario", default="credential_theft")
    parser.add_argument("--channel", default="PAGE")
    args = parser.parse_args()

    with TestClient(app) as client:
        response = client.post(
            "/demo/generate/alert",
            json={
                "tenant_id": args.tenant,
                "scenario": args.scenario,
                "notify_method": args.channel,
                "mode": "attack",
            },
        )
        response.raise_for_status()
        body = response.json()
        print(json.dumps(body, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
