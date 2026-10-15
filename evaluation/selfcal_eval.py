"""
Self-calibrated design (no dataset-level tuning): every operating point is derived from the entity's own calibration days.

    python -m evaluation.selfcal_eval <dataset> eval

Differences from the tuned design (evaluation/final_eval.py):
  * bound            (1 - alpha/4) quantile of the largest displacement over the horizon in B day-resampled clean futures,
                     in place of  margin * p99  with a margin tuned on development series;
  * floor            the fixed noise floor (0.5 scale units), in place of a floor tuned to a false-alert target;
  * sequential trigger  threshold = (1 - alpha/2) quantile of its largest value in the same resampled futures, in place of
                     a threshold tuned on development series;
  * default bound   (used when validation fails) is the median self-calibrated bound of the dataset's own entities.
Variants reported (all label-free):
  cal_ledger_B   displacement bound + hold + ledger, validation = alert exclusion + split-half trend + default fallback
  cal_ledger_Bc  the same plus the cohort p95 cross-check and the 1.5x cohort-median cap (statistics from the dataset's own entities)
  dual_B / dual_Bc  adds a second, sequential trigger whose threshold is self-calibrated in the same way
Only alpha (0.05) and the horizon are chosen by the operator.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys

import numpy as np

from evaluation.final_eval import (CONFIGS, DATASET, EV, FAMILY, OUT, ZCLIP, _prep, _s, build, label, scenarios)
from evaluation.margin_rule import selfcal
from evaluation.scenarios import Scenario, apply_scenario
from evaluation.simulate import run
from phase0.guard.calibration import MIN_BOUND

ALPHA = float(os.environ.get("SELFCAL_ALPHA", "0.05"))
B = int(os.environ.get("SELFCAL_B", "80"))
from phase0.guard import GuardConfig  # noqa: E402

LEDGER_FREEZE = GuardConfig(promotion_mode="ledger", freeze_on_hold=True)
# variant -> (strategy label, cohort checks, guard config override or None)
VARIANTS = {"B": ("cal_ledger", False, None), "Bc": ("cal_ledger", True, None), "Bf": ("cal_ledger", False, LEDGER_FREEZE),
            "dualB": ("dual", False, None), "dualBc": ("dual", True, None)}
B_CONFIGS = [(lab, {"dualB": "B", "dualBc": "Bc"}.get(v, v), cohort, cfg)
             for v in os.environ.get("SELFCAL_VARIANTS", "B,Bc,Bf,dualB,dualBc").split(",") for lab, cohort, cfg in [VARIANTS[v]]]
POISONED_CACHE = OUT / f"selfcal_poisoned_{DATASET}_{ALPHA}.json"
FLEET_CACHE = OUT / f"selfcal_fleet_{DATASET}_{ALPHA}.json"


def _fleet(args):
    idx, e = args
    cal = selfcal(e, e.values, B, ALPHA, seed=idx)
    r = run(e, Scenario("control"), "guard_probe")
    t = r.traces or {}
    return {"idx": idx, "cal": cal, "d_w": t.get("d_w", []), "d_c": t.get("d_c", []), "group": e.group}


def cohort_stats(fleet):
    by = {}
    for f in fleet:
        if len(f["d_c"]) >= 20:
            by.setdefault(f["group"], []).append(f)
    stats, raw_all = {}, []
    for g, items in by.items():
        aw = np.concatenate([np.asarray(i["d_w"]) for i in items])
        ac = np.concatenate([np.asarray(i["d_c"]) for i in items])
        raw = [(max(MIN_BOUND, i["cal"]["bw"]), max(MIN_BOUND, i["cal"]["bc"])) for i in items]
        raw_all += raw
        stats[g] = {"p95": (float(np.percentile(aw, 95)), float(np.percentile(ac, 95))),
                    "median_bound": (float(np.median([b[0] for b in raw])), float(np.median([b[1] for b in raw]))), "n": len(items)}
    stats["__global__"] = {"median_bound": (float(np.median([b[0] for b in raw_all])), float(np.median([b[1] for b in raw_all]))), "n": len(raw_all)}
    return stats


def _eval_one(args):
    idx, e, CS, clean_cal, meta, pois_cal = args
    out = {"id": e.entity_id, "source": e.source, "group": e.group, **meta, "self_cal": clean_cal, "res": {}}
    scs = scenarios(idx, e)
    cals = {}
    for lab, suffix, cohort, cfg_override in B_CONFIGS:
        strat, cfg, _ = CONFIGS[lab]
        cfg = cfg_override or cfg
        d = {}
        for name, (sc, corro) in scs.items():
            if sc.kind == "poisoned_cal":  # the calibration data differs, so the operating point is derived from it
                if "poisoned" not in cals:
                    cals["poisoned"] = pois_cal or selfcal(e, apply_scenario(e, sc), B, ALPHA, seed=10_000 + idx)
                    out["poisoned_cal"] = cals["poisoned"]
                cal = cals["poisoned"]
            else:
                cal = clean_cal
            kw = {"default_bounds": CS["__global__"]["median_bound"], "cohort_stats": CS.get(e.group) if cohort else None, "guard_config": cfg,
                  "raw_bounds": (cal["bw"], cal["bc"]), "cusum_h": cal["h"], "zclip": ZCLIP}
            if corro is not None:
                kw["corroborated"] = corro
            if lab == "cal_ledger":
                kw.pop("cusum_h"); kw.pop("zclip")
            d[name] = _s(lab, run(e, sc, strat, **kw))
        out["res"][f"{lab}_{suffix}"] = d
    return out


if __name__ == "__main__":
    E = build()
    print(DATASET, "self-calibrated, alpha", ALPHA, "B", B, "entities", len(E), flush=True)
    with mp.Pool(2) as pool:
        prep = pool.map(_prep, [(i, e, None) for i, e in enumerate(E)], chunksize=2)
        if FLEET_CACHE.exists():
            fleet = json.load(open(FLEET_CACHE))
        else:
            fleet = pool.map(_fleet, [(i, e) for i, e in enumerate(E)], chunksize=1)
            FLEET_CACHE.write_text(json.dumps(fleet))
        CS = cohort_stats(fleet)
        pc = json.load(open(POISONED_CACHE)) if POISONED_CACHE.exists() else {}
        rows = pool.map(_eval_one, [(i, E[i], CS, fleet[i]["cal"], prep[i], pc.get(str(i))) for i in range(len(E))], chunksize=1)
        POISONED_CACHE.write_text(json.dumps({str(i): r["poisoned_cal"] for i, r in enumerate(rows) if "poisoned_cal" in r}))
    (OUT / f"selfcal_{DATASET}_{ALPHA}.json").write_text(json.dumps({"alpha": ALPHA, "B": B, "cohort_stats": CS, "rows": rows}))
    print("done", len(rows))
