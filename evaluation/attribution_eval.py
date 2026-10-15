"""
Invention B, step 1 on real telemetry: does metric attribution name the metric that was moved, and does it matter
which baseline the attribution is computed against?

    python -m evaluation.attribution_eval <cs_dev|cs_fresh2|cs_fresh3|cs_fresh3a|cs_long>

Per resource with at least 3 eligible metrics, each metric is the target once. A scenario (stealth 2σ, stealth 3σ, fast 4σ)
is added to the target metric only; the other metrics of the resource are the real series (their own natural variation is the
distractor). At each probe day the last 24 hourly readings of every metric are standardised against a reference and passed to
the existing `MetricAttributor` (phase3/rca/metric_attribution.py, threshold 3.0, peak of 3-reading medians) with a constant
(level 0, scale 1) lookup, so the module's own ranking logic is used unchanged. Two references:

  snapshot  per-(hour, day type) median and robust scale of days 0-29, the trusted snapshot of claim 1, never updated here
  adaptive  per-(hour, day type) median and robust scale of the 30 most recent same-bucket readings before the observation
            day (the production rolling window), which has followed whatever the target metric has been doing

Protocol: docs/patent_evaluation/PREREG_UNIFIED_B.md. Nothing is tuned; thresholds are the module defaults.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

DATASET = sys.argv[1]
os.environ["EVAL_PROFILE"] = {"cs_dev": "corestack", "cs_fresh2": "corestack90", "cs_fresh3": "corestack90", "cs_fresh3a": "corestack90", "cs_long": "corestack_long"}[DATASET]
_argv = sys.argv
sys.argv = ["x", DATASET, "none"]
import numpy as np  # noqa: E402

import evaluation.final_eval as fe  # noqa: E402
from evaluation.data import SIM_START  # noqa: E402
from evaluation.scenarios import END_DAY, EVENT_DAY, Scenario, apply_scenario  # noqa: E402
from phase0.guard.drift_guard import robust_scale  # noqa: E402
from phase3.rca.metric_attribution import ConstantBaselineLookup, MetricAttributor  # noqa: E402
from shared.types import RawRecord  # noqa: E402

sys.argv = _argv
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/patent_evaluation"
LONG_RAMP = fe.LONG_RAMP
PROBES = (EVENT_DAY + 10, EVENT_DAY + LONG_RAMP + 5, END_DAY - 1)
SCEN = {
    "stealth2": lambda i: Scenario("attack", "linear", 2.0, ramp_days=LONG_RAMP, seed=i),
    "stealth3": lambda i: Scenario("attack", "linear", 3.0, ramp_days=LONG_RAMP, seed=i),
    "fast4": lambda i: Scenario("attack", "linear", 4.0, ramp_days=10, seed=i),
    "control": None,
}
ATTRS = {"pk3": MetricAttributor([], peak_window=3), "pk24": MetricAttributor([], peak_window=24)}
LOOK = ConstantBaselineLookup(level=0.0, scale=1.0)


WK0 = 0  # weekday offset of the resource being processed (Entity.wk0; 0 for the Monday-aligned sets)


def _daytype(day: int) -> int:
    return int((SIM_START + timedelta(days=day + WK0)).weekday() >= 5)


def _bucket_vals(values: np.ndarray, days, hour: int, dtype: int):
    return [values[d * 24 + hour] for d in days if _daytype(d) == dtype]


def _ref_snapshot(values: np.ndarray, hour: int, dtype: int):
    vals = _bucket_vals(values, range(0, 30), hour, dtype)
    return float(np.median(vals)), robust_scale(vals)


def _ref_adaptive(values: np.ndarray, hour: int, dtype: int, day: int):
    prior = [d for d in range(0, day) if _daytype(d) == dtype][-30:]
    vals = [values[d * 24 + hour] for d in prior]
    return float(np.median(vals)), robust_scale(vals)


def _contribs(series: dict, day: int, which: str, variant: str):
    recs = []
    for name, values in series.items():
        for h in range(24):
            ref = _ref_snapshot(values, h, _daytype(day)) if which == "snapshot" else _ref_adaptive(values, h, _daytype(day), day)
            med, sc = ref
            z = (float(values[day * 24 + h]) - med) / sc
            recs.append(RawRecord(entity_id="r", timestamp=SIM_START + timedelta(days=day, hours=h), cloud="Azure",
                                  entity_type="x", namespace="x", metric_name=name, value=z))
    res = ATTRS[variant].attribute(recs, LOOK)
    return {c.metric_name: (c.contribution, c.direction) for c in res.contributions}


def main():
    ents = fe.build()
    by = defaultdict(list)
    for e in ents:
        by[e.source].append(e)
    rows = []
    for rid in sorted(by):
        group = sorted(by[rid], key=lambda e: e.entity_id)
        if len(group) < 3:
            continue
        global WK0
        assert len({getattr(e, "wk0", 0) for e in group}) == 1, rid
        WK0 = getattr(group[0], "wk0", 0)
        for ti, tgt in enumerate(group):
            for sname, make in SCEN.items():
                base = {e.entity_id: np.asarray(e.values, float) for e in group}
                if make is not None:
                    base[tgt.entity_id] = apply_scenario(tgt, make(ti))
                for p in PROBES:
                    for which, variant in [(w, v) for v in ATTRS for w in ("snapshot", "adaptive")]:
                        c = _contribs(base, p, which, variant)
                        order = sorted(c, key=lambda m: (-c[m][0], m))
                        rank = order.index(tgt.entity_id) + 1 if tgt.entity_id in c else None
                        rows.append({
                            "resource": rid, "target": tgt.entity_id, "n_metrics": len(group), "scenario": sname, "probe": p,
                            "baseline": which, "variant": variant, "rank": rank, "target_contrib": c.get(tgt.entity_id, (None,))[0],
                            "target_dir": c.get(tgt.entity_id, (None, None))[1],
                            "n_flag_nontarget": sum(1 for m, (v, _) in c.items() if m != tgt.entity_id and v >= 3.0),
                            "n_flag_all": sum(1 for m, (v, _) in c.items() if v >= 3.0),
                        })
    (OUT / f"attribution_{DATASET}.json").write_text(json.dumps({"dataset": DATASET, "probes": PROBES, "rows": rows}))
    print(DATASET, "rows", len(rows), "resources", len({r["resource"] for r in rows}))


if __name__ == "__main__":
    main()
