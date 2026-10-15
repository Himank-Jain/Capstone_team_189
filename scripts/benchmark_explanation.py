#!/usr/bin/env python
"""Reproducibility, latency and locality of the deterministic explanation.

For each of the project's 18 synthetic scenarios the explanation pipeline
(metric attribution -> hypothesis rules -> confidence -> explanation ->
recommendations -> threat-signature match) is re-run N times from the same
input. Reports: share of runs whose full output is byte-identical to the
first, median/p95 latency, and the number of network connections attempted
(sockets are blocked during the timed runs).

Usage: PYTHONPATH=. python scripts/benchmark_explanation.py [--runs 556]
Writes docs/patent_evaluation/explanation_results.json
"""
import argparse
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
from phase3.api import app as app_module
from phase3.api.app import app
from phase3.api.routers import _support
from phase3.api.routers._support import provision_demo_identity, rca_cases

ROOT = Path(__file__).resolve().parents[1]


def explain(case):
    case = _copy_case(case)
    case.candidate_causes = _support.hypothesis_engine.generate(case)
    case.confidence = _support.ConfidenceScorer.score_case(case)
    explanation = _support.explanation_builder.build(case)
    recs = _support.recommendation_engine.recommend(case)
    matches = _support.threat_signature_matcher.match(case)
    return json.dumps(
        {"cause": jsonable_encoder(asdict(case.candidate_causes[0])),
         "explanation": jsonable_encoder(asdict(explanation)),
         "recommendations": jsonable_encoder([asdict(r) for r in recs]),
         "matches": jsonable_encoder([asdict(m) for m in matches])},
        sort_keys=True,
    )


def _copy_case(case):
    import copy
    return copy.deepcopy(case)


def attribute(gen, scenario_id, seed):
    recs = gen.generate_events(scenario_id, "AWS", "medium", entity_id="bench", seed=seed)
    res = app_module._METRIC_ATTRIBUTOR.attribute(recs, app_module._DEMO_BASELINE_LOOKUP)
    return json.dumps(jsonable_encoder(asdict(res)), sort_keys=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=556)  # 18 x 556 = 10,008 runs
    args = ap.parse_args()
    provision_demo_identity()
    gen = DemoGenerator()
    cases = {}
    with TestClient(app) as client:
        for sc in gen.scenarios.values():
            h = {"X-Tenant-Id": "amazon", "X-User-Id": "demo-user"}
            client.post("/demo/reset", headers=h).raise_for_status()
            r = client.post("/demo/generate/alert", headers=h, json={
                "tenant_id": "amazon", "scenario": sc.scenario_id, "cloud_provider": "AWS",
                "intensity": "medium", "seed": sc.seed, "notify_method": "PAGE"})
            r.raise_for_status()
            cases[sc.scenario_id] = (rca_cases["amazon"][r.json()["alert_payload"]["alert_id"]], sc.seed)

    attempts = {"n": 0}
    real_socket = socket.socket

    class Blocked(real_socket):
        def connect(self, *a, **k):
            attempts["n"] += 1
            raise OSError("network blocked for benchmark")

    socket.socket = Blocked
    latencies, identical, total = [], 0, 0
    attr_identical = 0
    per_scenario = {}
    try:
        for sid, (case, seed) in cases.items():
            first = explain(case)
            first_attr = attribute(gen, sid, seed)
            same = 0
            for _ in range(args.runs):
                t0 = time.perf_counter()
                out = explain(case)
                a_out = attribute(gen, sid, seed)
                latencies.append((time.perf_counter() - t0) * 1000.0)
                total += 1
                same += out == first and a_out == first_attr
            identical += same
            per_scenario[sid] = same
    finally:
        socket.socket = real_socket

    latencies.sort()
    result = {
        "scenarios": len(cases), "runs_total": total, "identical_runs": identical,
        "identical_pct": 100.0 * identical / total,
        "latency_ms_median": statistics.median(latencies),
        "latency_ms_p95": latencies[int(0.95 * (len(latencies) - 1))],
        "network_connection_attempts": attempts["n"],
        "output_sha256_of_first_scenario": hashlib.sha256(
            explain(next(iter(cases.values()))[0]).encode()).hexdigest()[:16],
    }
    out = ROOT / "docs" / "patent_evaluation"
    out.mkdir(parents=True, exist_ok=True)
    (out / "explanation_results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
