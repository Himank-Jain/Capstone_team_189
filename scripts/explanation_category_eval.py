"""
Cause-category accuracy of the deterministic threat-signature matcher, on the same 810 held-out synthetic runs as
scripts/evaluate_explanation_heldout.py (18 scenarios x 5 seeds x 3 intensities x 3 clouds).  The frozen rules are not changed.

The matcher names one of 17 signatures (or nothing).  The deck's "correct cause category" is a coarser question, so the grouping below
was written down BEFORE this script was run and is not changed afterwards:

  identity_access   credential_theft, brute_force_login, insider_threat, lateral_movement
  data_integrity    data_exfiltration, ransomware, log_tampering
  workload_abuse    malware_execution, rogue_resources, function_abuse
  network_exposure  network_scan, ddos_volumetric, public_exposure
  benign_change     benign_baseline, planned_deployment, organic_growth, provider_regional_event
  UNKNOWN           ambiguous_change (a correct answer is "no signature matches")

Predicted category = category of the top-1 signature, UNKNOWN when nothing matches.  Per-run results are stored so that the
confusion can be read; the scenario definitions are shared with the rules, so this tests robustness to noise, intensity and cloud, not
independence of the scenario authors (same limit as the 810-run top-1 / top-3 figures).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from fastapi.testclient import TestClient

from demo_generator.generator import DemoGenerator
from phase3.api.app import app
from phase3.api.routers._support import provision_demo_identity, rca_cases
from phase3.knowledge.threat_signature_matcher import ThreatSignatureMatcher

SEEDS = [9001, 9002, 9003, 9004, 9005]
INTENSITIES = ["low", "medium", "high"]
CLOUDS = ["AWS", "Azure", "GCP"]
GROUP = {
    "credential_theft": "identity_access", "brute_force_login": "identity_access", "insider_threat": "identity_access", "lateral_movement": "identity_access",
    "data_exfiltration": "data_integrity", "ransomware": "data_integrity", "log_tampering": "data_integrity",
    "malware_execution": "workload_abuse", "rogue_resources": "workload_abuse", "function_abuse": "workload_abuse",
    "network_scan": "network_exposure", "ddos_volumetric": "network_exposure", "public_exposure": "network_exposure",
    "benign_baseline": "benign_change", "planned_deployment": "benign_change", "organic_growth": "benign_change", "provider_regional_event": "benign_change",
    "ambiguous_change": "UNKNOWN",
}


def main() -> None:
    provision_demo_identity()
    gen = DemoGenerator()
    matcher = ThreatSignatureMatcher()
    runs = []
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
                        top1 = m[0].threat_id if m else None
                        truth = GROUP[sc.scenario_id]
                        pred = GROUP.get(top1, "UNKNOWN") if top1 else "UNKNOWN"
                        runs.append({"scenario": sc.scenario_id, "seed": seed, "intensity": inten, "cloud": cloud, "top1": top1,
                                     "top3": [x.threat_id for x in m[:3]], "truth": truth, "pred": pred})
    n = len(runs)
    ok = sum(r["truth"] == r["pred"] for r in runs)
    per = defaultdict(lambda: [0, 0])
    for r in runs:
        per[r["truth"]][0] += 1
        per[r["truth"]][1] += int(r["truth"] == r["pred"])
    conf = Counter((r["truth"], r["pred"]) for r in runs)
    out = {"runs": n, "category_correct": ok, "per_category": {k: {"n": v[0], "correct": v[1]} for k, v in per.items()},
           "confusion": {f"{a}->{b}": c for (a, b), c in sorted(conf.items())}, "group": GROUP, "per_run": runs}
    Path("docs/patent_evaluation/explanation_category.json").write_text(json.dumps(out, indent=1))
    print(f"runs {n}  category correct {ok} ({ok / n:.1%})")
    for k, v in per.items():
        print(f"  {k:18s} {v[1]}/{v[0]}")
    print("confusions:", {k: c for k, c in out["confusion"].items() if k.split('->')[0] != k.split('->')[1]})


if __name__ == "__main__":
    main()
