"""
Alert collapsing during a hold: how many alert-days would the operator see without it, against how many incidents with it.

    python -m evaluation.collapse_eval <dataset> eval

For the design (self-calibrated bound, validated, freeze-on-hold, ledgered capped promotion; the `full` variant of ablation_eval) on the
attack, benign and control scenarios, per run: incidents opened after the event day, flag-days after the event day that an
uncollapsed alerting would have raised (days with at least FLAGS_PER_ALERT_DAY ordinary z-flags), the share of those that attached to
an already open incident, and the number of days held. Same entities, scenarios and frozen design as the ablation.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os

from evaluation.ablation_eval import ABLATION, _scenarios
from evaluation.final_eval import DATASET, EV, FAMILY, OUT, _prep, build, frozen, thresholds
from evaluation.lit_attacks import lit_scenarios  # noqa: F401
from evaluation.margin_rule import selfcal
from evaluation.scenarios import apply_scenario
from evaluation.selfcal_eval import ALPHA, B, FLEET_CACHE, POISONED_CACHE, cohort_stats
from evaluation.simulate import run

KEEP = ("control", "stealth2.0", "stealth3.0", "fast4", "benign", "greedy")


def _one(args):
    idx, e, CS, clean_cal, meta, pois_cal, th = args
    strat, cfg, spec_lab, kwf = ABLATION["full"]
    out = {"id": e.entity_id, "source": e.source, "group": e.group, **meta, "runs": {}}
    for name, (sc, corro) in _scenarios(idx, e).items():
        if name not in KEEP:
            continue
        kw = kwf(clean_cal, CS, th)
        kw["guard_config"] = cfg
        if corro is not None:
            kw["corroborated"] = corro
        r = run(e, sc, strat, **kw)
        inc = sorted(d for d in r.incident_days if d >= EV)
        flags = sorted(d for d in r.flag_days if d >= EV)
        col = sorted(d for d in r.collapsed_days if d >= EV)
        out["runs"][name] = {"incidents": inc, "flag_days": flags, "collapsed": col,
                              "held_days": len([d for d in r.held_end_days if d >= EV])}
    return out


if __name__ == "__main__":
    E = build()
    th = thresholds(frozen()[f"{FAMILY}_dev"], float(os.environ.get("FPR_TARGET", "0.05")))
    fleet = json.load(open(FLEET_CACHE))
    CS = cohort_stats(fleet)
    pc = json.load(open(POISONED_CACHE)) if POISONED_CACHE.exists() else {}
    with mp.Pool(2) as pool:
        prep = pool.map(_prep, [(i, e, None) for i, e in enumerate(E)], chunksize=2)
        rows = pool.map(_one, [(i, E[i], CS, fleet[i]["cal"], prep[i], pc.get(str(i)), th) for i in range(len(E))], chunksize=1)
    (OUT / f"collapse_{DATASET}.json").write_text(json.dumps({"rows": rows}))
    print("done", DATASET, len(rows))
