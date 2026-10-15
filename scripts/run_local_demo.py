"""Run the complete synthetic alert flow without cloud credentials."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep the repository-root bootstrap above local imports for direct invocation.
from phase3.api.app import app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="amazon")
    parser.add_argument("--scenario", default="credential_theft")
    parser.add_argument("--channel", default="PAGE")
    args = parser.parse_args()

    with TestClient(app) as client:
        login_response = client.post(
            "/auth/login",
            json={"email": "demo@capstone189.local", "password": "demo"},
        )
        login_response.raise_for_status()
        user_id = login_response.json()["user"]["user_id"]
        response = client.post(
            "/demo/generate/alert",
            headers={"X-Tenant-Id": args.tenant, "X-User-Id": user_id},
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
