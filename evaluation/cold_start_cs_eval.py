"""
Cohort-seeding cold start on real CoreStack series (the earlier test used 16 NAB entities).

    python -m evaluation.cold_start_cs_eval <cs_dev|cs_fresh2>

Same protocol as evaluation/cold_start_eval.py (a "new" entity streams hourly readings from hour 0 of a Monday-aligned window; the
seeded variant borrows the shape of OTHER resources of the same metric group after 24 readings; an injected persistent +4 scale-unit
shift at hour 48; scoring start, detection delay, false alerts per 100 scored readings). Cohort = every other resource with the same
(entity type, metric); groups with fewer than 3 resources are skipped. Cross-cloud seeding is not tested: within a group all
resources share a cloud.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

DATASET = sys.argv[1]
os.environ["EVAL_PROFILE"] = {"cs_dev": "corestack", "cs_fresh2": "corestack90"}[DATASET]
_argv = sys.argv
sys.argv = ["x", DATASET, "none"]
import numpy as np  # noqa: E402

import evaluation.final_eval as fe  # noqa: E402
from evaluation.cold_start_eval import HOURS, SHIFT_AT, _run  # noqa: E402
from evaluation.data import SIM_START  # noqa: E402
from phase0.baseline.cohort_seeding import build_cohort_shape, robust_level_scale  # noqa: E402

sys.argv = _argv
OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"


def main():
    ents = fe.build()
    by_group = defaultdict(list)
    for e in ents:
        by_group[e.group].append(e)
    rows = []
    for g, es in sorted(by_group.items()):
        if len({e.source for e in es}) < 3:
            continue
        for e in es:
            cohort = {c.source: c for c in es if c.source != e.source}
            hist = []
            for c in cohort.values():
                h = []
                for d in range(30, min(89, len(c.values) // 24)):
                    for hr in range(24):
                        t = SIM_START + timedelta(days=d, hours=hr)
                        h.append((t.hour, t.weekday() >= 5, float(c.values[d * 24 + hr])))
                hist.append(h)
            try:
                shape = build_cohort_shape(hist)
            except ValueError:
                continue
            start = 28 * 24
            vals = e.values[start:start + HOURS]
            if len(vals) < HOURS:
                continue
            scale_ref = robust_level_scale(e.values[start:start + 24 * 14])[1]
            out = {"entity": e.entity_id, "group": g, "resource": e.source}
            for name, seeded in (("unseeded", False), ("seeded", True)):
                sc, _ = _run(vals, seeded, shape, False, scale_ref)
                _, al_clean = _run(vals, seeded, shape, False, scale_ref)
                _, al_shift = _run(vals, seeded, shape, True, scale_ref)
                start_h = next((i for i in range(0, HOURS - 24) if sum(sc[i:i + 24]) >= 12), None)
                scored_clean = sum(sc[24:])
                fa = 100.0 * sum(al_clean[24:]) / max(1, scored_clean)
                det = next((i - SHIFT_AT for i in range(SHIFT_AT, HOURS) if al_shift[i]), None)
                out[name] = {"scoring_start_h": start_h, "detect_delay_h": det, "false_alerts_per_100": fa}
            rows.append(out)
    res = {"dataset": DATASET, "n_entities": len(rows), "n_resources": len({r["resource"] for r in rows}), "rows": rows}
    for name in ("unseeded", "seeded"):
        st = [r[name]["scoring_start_h"] for r in rows if r[name]["scoring_start_h"] is not None]
        dl = [r[name]["detect_delay_h"] for r in rows if r[name]["detect_delay_h"] is not None]
        fa = [r[name]["false_alerts_per_100"] for r in rows]
        res[name] = {"scored_within_10d": len(st), "scoring_start_h_median": statistics.median(st) if st else None,
                     "detected_k": len(dl), "detect_delay_h_median": statistics.median(dl) if dl else None,
                     "false_alerts_per_100_median": statistics.median(fa), "false_alerts_per_100_mean": float(np.mean(fa))}
    json.dump(res, open(OUT / f"cold_start_{DATASET}.json", "w"), indent=1)
    print(DATASET, "entities", res["n_entities"], "resources", res["n_resources"])
    for k in ("unseeded", "seeded"):
        print(k, json.dumps(res[k]))


if __name__ == "__main__":
    main()
