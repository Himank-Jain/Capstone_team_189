"""Paired summary of cold_start_<ds>.json: detection within the window, false alerts, bootstrap over resources.

    python -m evaluation.cold_start_report <cs_dev|cs_fresh2>
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"
RNG = np.random.default_rng(20261015)


def _boot(by_res, stat, n=2000):
    keys = sorted(by_res)
    v = []
    for _ in range(n):
        pick = RNG.integers(0, len(keys), len(keys))
        v.append(stat([r for i in pick for r in by_res[keys[i]]]))
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def main(ds: str):
    d = json.loads((OUT / f"cold_start_{ds}.json").read_text())
    rows = d["rows"]
    by = defaultdict(list)
    for r in rows:
        by[r["resource"]].append(r)
    det = lambda k: (lambda rs: float(np.mean([x[k]["detect_delay_h"] is not None for x in rs])))
    fa = lambda k: (lambda rs: float(np.mean([x[k]["false_alerts_per_100"] for x in rs])))
    ddet = lambda rs: det("seeded")(rs) - det("unseeded")(rs)
    dfa = lambda rs: fa("seeded")(rs) - fa("unseeded")(rs)
    dstart = lambda rs: float(np.median([x["unseeded"]["scoring_start_h"] - x["seeded"]["scoring_start_h"] for x in rs]))
    out = {"dataset": ds, "n": len(rows), "resources": len(by)}
    for k in ("unseeded", "seeded"):
        out[k] = {"detected": det(k)(rows), "detected_ci": _boot(by, det(k)), "false_alerts_per_100_mean": fa(k)(rows),
                  "false_alerts_ci": _boot(by, fa(k))}
    out["paired_detected_diff"] = ddet(rows)
    out["paired_detected_diff_ci"] = _boot(by, ddet)
    out["paired_false_alert_diff"] = dfa(rows)
    out["paired_false_alert_diff_ci"] = _boot(by, dfa)
    out["median_hours_saved_to_scoring"] = dstart(rows)
    # seeded entities that false-alert badly
    out["seeded_fa_over_10_share"] = float(np.mean([r["seeded"]["false_alerts_per_100"] > 10 for r in rows]))
    out["unseeded_fa_over_10_share"] = float(np.mean([r["unseeded"]["false_alerts_per_100"] > 10 for r in rows]))
    print(json.dumps(out, indent=1))
    (OUT / f"cold_start_summary_{ds}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
