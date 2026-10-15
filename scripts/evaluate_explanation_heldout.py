"""
Held-out evaluation of threat-signature matching.

The 18-scenario report (docs/threat_signature_accuracy.md) uses each scenario's
own seed at medium intensity on AWS: the setting the rules were written and
checked against. This script evaluates the SAME frozen rules on settings never
used while writing them: 5 fresh seeds x 3 intensities x 3 clouds per scenario
(45 runs each). No rule or signature is changed by this script.

Limit: scenario definitions (which metrics move, in which direction) are shared
with the rules, so this tests robustness to noise, intensity and cloud, not
independence of the scenario authors.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from fastapi.testclient import TestClient

from demo_generator.generator import DemoGenerator
from phase3.api.app import app
from phase3.api.routers._support import provision_demo_identity, rca_cases
from phase3.knowledge.threat_signature_matcher import ThreatSignatureMatcher

SEEDS = [9001, 9002, 9003, 9004, 9005]
INTENSITIES = ["low", "medium", "high"]
CLOUDS = ["AWS", "Azure", "GCP"]


def main() -> None:
    provision_demo_identity()
    gen = DemoGenerator()
    matcher = ThreatSignatureMatcher()
    per = defaultdict(lambda: [0, 0, 0])  # n, top1, top3
    by_int = defaultdict(lambda: [0, 0, 0])
    by_cloud = defaultdict(lambda: [0, 0, 0])
    with TestClient(app) as client:
        for sc in gen.scenarios.values():
            for seed in SEEDS:
                for inten in INTENSITIES:
                    for cloud in CLOUDS:
                        h = {"X-Tenant-Id": "amazon", "X-User-Id": "demo-user"}
                        client.post("/demo/reset", headers=h).raise_for_status()
                        r = client.post("/demo/generate/alert", headers=h, json={
                            "tenant_id": "amazon", "scenario": sc.scenario_id, "cloud_provider": cloud,
                            "intensity": inten, "seed": seed, "notify_method": "PAGE"})
                        if r.status_code != 200:
                            continue
                        aid = r.json()["alert_payload"]["alert_id"]
                        case = rca_cases.get("amazon", {}).get(aid)
                        if case is None:
                            continue
                        m = matcher.match(case)
                        if sc.category == "ambiguous":
                            t1 = t3 = not m
                        else:
                            t1 = bool(m) and m[0].threat_id == sc.scenario_id
                            t3 = any(x.threat_id == sc.scenario_id for x in m[:3])
                        for d, k in ((per, sc.scenario_id), (by_int, inten), (by_cloud, cloud)):
                            d[k][0] += 1
                            d[k][1] += int(t1)
                            d[k][2] += int(t3)
    n = sum(v[0] for v in per.values())
    out = {
        "runs": n,
        "top1": sum(v[1] for v in per.values()), "top3": sum(v[2] for v in per.values()),
        "per_scenario": {k: {"n": v[0], "top1": v[1], "top3": v[2]} for k, v in per.items()},
        "by_intensity": {k: {"n": v[0], "top1": v[1], "top3": v[2]} for k, v in by_int.items()},
        "by_cloud": {k: {"n": v[0], "top1": v[1], "top3": v[2]} for k, v in by_cloud.items()},
    }
    Path("docs/patent_evaluation/explanation_heldout.json").write_text(json.dumps(out, indent=1))
    print(f"runs {n}  top1 {out['top1']} ({out['top1']/n:.1%})  top3 {out['top3']} ({out['top3']/n:.1%})")
    for k, v in out["by_intensity"].items():
        print(k, v)
    for k, v in out["by_cloud"].items():
        print(k, v)
    for k, v in out["per_scenario"].items():
        print(f"{k:24s} {v['top1']}/{v['n']} {v['top3']}/{v['n']}")


if __name__ == "__main__":
    main()
