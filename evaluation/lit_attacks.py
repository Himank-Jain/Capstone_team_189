"""
Attacks specified by other people, run against the frozen design.

    python -m evaluation.lit_attacks <dataset> eval

These are NOT third-party attack data. They are attack strategies taken from the literature, implemented by us with the
parameters those papers report, and applied to real or day-resampled benign series:

  frog1.01 ... frog1.15   Rubinstein et al., ANTIDOTE, IMC 2009: the attacked metric's average level grows by a factor g
                          every week (g = 1.01, 1.02, 1.05, 1.15, the values in that paper), starting at the event day.
  greedy                  Kloft & Laskov, JMLR 2012, greedy optimal attack on an online centroid detector: every injected
                          reading is placed at the edge of the detector's acceptance region (z = 2.9 against the threshold
                          of 3), the closed-loop optimum, until the stored baseline has moved by the attacker's goal
                          (6 scale units); the attacker only adds load.

Thresholds are the ones frozen from development data (frozen_design.json); nothing is tuned on the dataset being run.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys

import numpy as np

from evaluation.final_eval import (CONFIGS, DATASET, EV, FAMILY, OUT, ZCLIP, _prep, _s, build, frozen, kwargs_for, thresholds,
                                   tuned_block)
from evaluation.scenarios import END_DAY, EVENT_DAY, Scenario
from evaluation.simulate import run

GREEDY_K, GREEDY_GOAL = 2.9, 6.0
GROWTH = (1.01, 1.02, 1.05, 1.15)
LIT_CONFIGS = ("adaptive", "frozen", "rollback", "clip", "cusum_r", "cal_ledger", "dual")


def lit_scenarios(idx):
    sc = {f"frog{g}": Scenario("frog", "", g, start=EVENT_DAY, seed=idx) for g in GROWTH}
    sc["greedy"] = Scenario("greedy", "", GREEDY_K, start=EVENT_DAY, payload=GREEDY_GOAL, seed=idx)
    return sc


def _one(args):
    idx, e, T, th, meta, SC = args
    weeks = (END_DAY - EVENT_DAY) / 7.0
    base = float(np.mean(e.values[: 30 * 24])) / max(e.hour_scale, 1e-9)
    out = {"id": e.entity_id, "source": e.source, "group": e.group, **meta,
           "frog_sigma": {f"frog{g}": float(abs(base) * (g ** weeks - 1.0)) for g in GROWTH}, "res": {}}
    for lab in LIT_CONFIGS:
        strat, cfg, _keys = CONFIGS[lab]
        d = {}
        for name, sc in lit_scenarios(idx).items():
            kw = kwargs_for(lab, strat, e, T, th)
            if cfg is not None:
                kw["guard_config"] = cfg
            r = run(e, sc, strat, **kw)
            row = _s(lab, r)
            row["goal_day"] = r.goal_day
            row["max_drift"] = max(r.drift_daily) if r.drift_daily else 0.0
            d[name] = row
        out["res"][lab] = d
    if SC is not None:  # self-calibrated design: thresholds come from the entity's own history (selfcal_eval output)
        cal, CS = SC["rows"][idx]["self_cal"], SC["cohort_stats"]
        from evaluation.selfcal_eval import B_CONFIGS
        for lab, suffix, cohort, cfg_override in [v for v in B_CONFIGS if v[0] == "cal_ledger"]:
            strat, cfg, _keys = CONFIGS[lab]
            cfg = cfg_override or cfg
            d = {}
            for name, sc in lit_scenarios(idx).items():
                kw = {"default_bounds": CS["__global__"]["median_bound"], "cohort_stats": CS.get(e.group) if cohort else None,
                      "guard_config": cfg, "raw_bounds": (cal["bw"], cal["bc"])}
                r = run(e, sc, strat, **kw)
                row = _s(lab, r)
                row["goal_day"] = r.goal_day
                row["max_drift"] = max(r.drift_daily) if r.drift_daily else 0.0
                d[name] = row
            out["res"][f"{lab}_{suffix}"] = d
    return out


if __name__ == "__main__":
    E = build()
    T = tuned_block()
    target = float(os.environ.get("FPR_TARGET", "0.05"))
    th = thresholds(frozen()[f"{FAMILY}_dev"], target)
    sc_file = OUT / f"selfcal_{DATASET}_{os.environ.get('SELFCAL_ALPHA', '0.05')}.json"
    SC = json.load(open(sc_file)) if sc_file.exists() else None
    print(DATASET, "self-calibrated results" if SC else "no self-calibrated results", "entities", len(E), "series", len({e.source for e in E}), "thresholds", th, flush=True)
    with mp.Pool(2) as pool:
        prep = pool.map(_prep, [(i, e, T) for i, e in enumerate(E)], chunksize=2)
        rows = pool.map(_one, [(i, e, T, th, prep[i], SC) for i, e in enumerate(E)], chunksize=2)
    (OUT / f"lit_{DATASET}_{target}.json").write_text(json.dumps({"thresholds": th, "rows": rows}))
    print("done", len(rows))
