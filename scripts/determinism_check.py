"""
Reproducibility and latency of the deterministic explanation chain (`ExplanationBuilder.build`: hypothesis rules, confidence,
threat signatures, knowledge base), measured here rather than assumed.

    PYTHONPATH=. python scripts/determinism_check.py

For each of the demo generator's scenarios x 3 clouds, one alert is generated through the API, the RCA case is taken from the
API's store, and `ExplanationBuilder.build` is run REPEATS times on the identical case. Every output is serialised with sorted keys
and hashed. Reported: runs, distinct hashes per case (1 = identical), median and p95 latency of one build, and whether the process
made any network connection (sockets are patched to fail). Process-level determinism only: the same interpreter, the same
rules and knowledge-base files. Writes docs/patent_evaluation/determinism_check.json.
"""
from __future__ import annotations

import hashlib
import json
import socket
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from demo_generator.generator import DemoGenerator
from phase3.api.app import app
from phase3.api.routers import _support
from phase3.api.routers._support import provision_demo_identity, rca_cases

REPEATS = 250
CLOUDS = ["AWS", "Azure", "GCP"]


def main() -> None:
    provision_demo_identity()
    gen = DemoGenerator()
    cases = []
    with TestClient(app) as client:
        for sc in gen.scenarios.values():
            for cloud in CLOUDS:
                h = {"X-Tenant-Id": "amazon", "X-User-Id": "demo-user"}
                client.post("/demo/reset", headers=h).raise_for_status()
                r = client.post("/demo/generate/alert", headers=h, json={
                    "tenant_id": "amazon", "scenario": sc.scenario_id, "cloud_provider": cloud,
                    "intensity": "medium", "seed": 9101, "notify_method": "PAGE"})
                if r.status_code != 200:
                    continue
                aid = r.json()["alert_payload"]["alert_id"]
                rec = rca_cases.get("amazon", {}).get(aid)
                if rec is not None:
                    cases.append((sc.scenario_id, cloud, rec))
    # no network from here on
    real_socket = socket.socket

    class _NoNet(real_socket):
        def connect(self, *a, **k):  # pragma: no cover
            raise OSError("network disabled for determinism check")

    socket.socket = _NoNet
    distinct, lat, total = [], [], 0
    try:
        for sid, cloud, case in cases:
            hashes = set()
            for _ in range(REPEATS):
                t = time.perf_counter()
                exp = _support.explanation_builder.build(case)
                lat.append((time.perf_counter() - t) * 1000.0)
                hashes.add(hashlib.sha256(json.dumps(jsonable_encoder(asdict(exp)), sort_keys=True).encode()).hexdigest())
                total += 1
            distinct.append(len(hashes))
    finally:
        socket.socket = real_socket
    lat.sort()
    out = {"cases": len(cases), "repeats_per_case": REPEATS, "runs": total, "cases_with_one_distinct_output": sum(1 for d in distinct if d == 1),
           "max_distinct_outputs_per_case": max(distinct) if distinct else None,
           "median_ms": statistics.median(lat), "p95_ms": lat[int(0.95 * len(lat))], "network_blocked": True}
    Path("docs/patent_evaluation/determinism_check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
