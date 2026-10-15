"""
Collect the daily mean residual (reading minus trusted snapshot, in snapshot scale units) of every entity under a fixed
list of scenarios, so that sequential triggers can be compared offline in seconds.

    python -m evaluation.xbar_collect <dataset>          datasets as in evaluation/final_eval.py (cs_dev, cs_fresh2, cs_fresh3, ...)

The residual against the trusted snapshot does not depend on the baseline's state, so one run per (entity, scenario)
with the guard's bounds open (strategy guard_dualprobe, trigger switched off) gives the series every trigger would see.
Output: docs/patent_evaluation/xbar_<dataset>.json  {meta: [...], x: {idx: {scenario: [daily means from SNAPSHOT_DAY]}}}
"""
from __future__ import annotations

import json
import multiprocessing as mp
import sys

DATASET = sys.argv[1]
sys.argv = ["x", DATASET, "none"]  # final_eval reads argv at import

from evaluation.final_eval import OUT, ZCLIP, _prep, build, label  # noqa: E402
from evaluation.scenarios import END_DAY, EVENT_DAY, SNAPSHOT_DAY, Scenario  # noqa: E402
from evaluation.simulate import run  # noqa: E402

DECK_PROFILES = ("linear", "stepped", "noise_masked")
DECK_SIGMA_TOTAL = (0.15, 0.30, 0.60, 0.90)  # 0.5, 1, 2, 3 percent of one hour-scale unit per day, 30 days
DECK_LEVEL_RATE = (0.005, 0.01, 0.02, 0.03)  # fraction of the entity's own mean level per day, 30 days
SIGMA_TOTAL = (1.0, 2.0, 3.0, 4.0)  # total shift after 30 days, in hour-scale units


def scenario_list(idx: int):
    sc = {"control": Scenario("control")}
    for p in DECK_PROFILES:
        for t in DECK_SIGMA_TOTAL:
            sc[f"R1_{p}_{t}"] = Scenario("attack", p, t, ramp_days=30, seed=idx)
        for r in DECK_LEVEL_RATE:
            sc[f"R2_{p}_{r}"] = Scenario("attack", p, r * 30, ramp_days=30, seed=idx, unit="level")
    for t in SIGMA_TOTAL:
        sc[f"S30_linear_{t}"] = Scenario("attack", "linear", t, ramp_days=30, seed=idx)
    sc["fast4"] = Scenario("attack", "linear", 4.0, ramp_days=10, seed=idx)
    for m in (0.5, 1.0, 2.0, 3.0):  # benign level shift, ramp 7 days (permanent)
        sc[f"benign_{m}"] = Scenario("benign", "linear", m, ramp_days=7, seed=idx)
    return sc


def _one(args):
    idx, e = args
    out = {}
    for name, sc in scenario_list(idx).items():
        r = run(e, sc, "guard_dualprobe", cusum_h=1e18, zclip=ZCLIP)
        out[name] = [round(r.xbar.get(d, float("nan")), 5) for d in range(SNAPSHOT_DAY, END_DAY)]
        out[name + "#med"] = [round(r.xmed.get(d, float("nan")), 5) for d in range(SNAPSHOT_DAY, END_DAY)]
        out[name + "#trim"] = [round(r.xtrim.get(d, float("nan")), 5) for d in range(SNAPSHOT_DAY, END_DAY)]
    return idx, out


if __name__ == "__main__":
    E = build()
    print(DATASET, "entities", len(E), "series", len({e.source for e in E}), flush=True)
    with mp.Pool(2) as pool:
        prep = pool.map(_prep, [(i, e, None) for i, e in enumerate(E)], chunksize=2)
        res = dict(pool.map(_one, [(i, e) for i, e in enumerate(E)], chunksize=2))
    meta = [{"idx": i, "id": e.entity_id, "source": e.source, "group": e.group, "wk0": getattr(e, "wk0", 0), **prep[i]} for i, e in enumerate(E)]
    (OUT / f"xbar_{DATASET}.json").write_text(json.dumps({"snapshot_day": SNAPSHOT_DAY, "end_day": END_DAY, "event_day": EVENT_DAY,
                                                          "meta": meta, "x": {str(k): v for k, v in res.items()}}))
    print("done", len(res))
