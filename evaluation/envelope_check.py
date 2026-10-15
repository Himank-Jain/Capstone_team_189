"""
End-to-end envelope check for the self-calibrated, freeze-on-hold design (variant Bf).

Statement being tested.  With freeze-on-hold no reading reaches the live baseline between a breach and the next promotion, so
the live baseline's displacement from the day-30 trusted snapshot after k promotion steps should not exceed
    (k + 1) * bound_c + sum of the k step sizes          (each cycle can move up to the bound before the freeze,
                                                           and each promotion step by at most its allowance)
in the entity's own scale units.  This is a statement about the whole displacement, not only about promotion.
It is checked, not proved: re-taking the snapshot re-estimates the scale, and the drift series is measured against the original
day-30 scale, so exceedances are possible and are counted.

    python -m evaluation.envelope_check <dataset>        (needs selfcal_<dataset>_0.05.json)
"""
from __future__ import annotations
import json, multiprocessing as mp, os, sys
DATASET = sys.argv[1]
sys.argv = [sys.argv[0], DATASET, "tune"]
os.environ["EVAL_PROFILE"] = {"cs_dev": "corestack", "cs_fresh2": "corestack90"}.get(DATASET, "")
import numpy as np
from evaluation.final_eval import OUT, build, scenarios, label
from evaluation.lit_attacks import lit_scenarios
from evaluation.simulate import run, day_epoch
from evaluation.scenarios import SNAPSHOT_DAY
from evaluation.selfcal_eval import LEDGER_FREEZE
from phase0.guard.calibration import MIN_BOUND

SC = json.load(open(OUT / f"selfcal_{DATASET}_0.05.json"))
CS = SC["cohort_stats"]
TOL = 0.05  # scale units of measurement tolerance


def one(args):
    i, e = args
    row = SC["rows"][i]
    if not (row["stable"] and row["ambient_free"]):
        return None
    cal = row["self_cal"]
    scs = {k: v[0] for k, v in scenarios(i, e).items() if k in ("stealth3.0", "fast4", "benign")}
    scs.update(lit_scenarios(i))
    out = []
    for name, sc in scs.items():
        r = run(e, sc, "guard_cal", guard_config=LEDGER_FREEZE, default_bounds=CS["__global__"]["median_bound"], cohort_stats=None,
                raw_bounds=(cal["bw"], cal["bc"]))
        bound = r.bounds[1]
        steps = sorted((x for x in r.ledger if "step" in x), key=lambda x: x["day"])
        worst, over = 0.0, 0
        for d, disp in enumerate(r.drift_daily):
            day = SNAPSHOT_DAY + d
            done = [abs(x["step"]) for x in steps if x["day"] <= day_epoch(day)]
            env = (len(done) + 1) * bound + sum(done) + TOL
            worst = max(worst, disp / env)
            over += disp > env
        a0, ac, ae = LEDGER_FREEZE.allow_base, LEDGER_FREEZE.allow_cohort, LEDGER_FREEZE.allow_corroborated
        ratios = []
        for x in steps:
            ev = x.get("evidence", [])
            allow = (a0 + (ac if "cohort" in ev else 0.0) + (ae if "change_event" in ev else 0.0)) * bound
            ratios.append(abs(x["step"]) / allow if allow else 0.0)
        gaps = [q["day"] - p["day"] for p, q in zip(steps, steps[1:])]
        out.append({"scenario": name, "step_ratios": ratios, "gaps": gaps, "bound": bound, "steps": len(steps), "max_ratio": worst, "days_over": over, "final": r.drift_daily[-1] if r.drift_daily else 0.0})
    return {"source": e.source, "id": e.entity_id, "runs": out}


if __name__ == "__main__":
    E = build()
    with mp.Pool(2) as pool:
        res = [r for r in pool.map(one, list(enumerate(E)), chunksize=2) if r]
    runs = [(r["source"], x) for r in res for x in r["runs"]]
    by = {}
    for src, x in runs:
        by.setdefault(x["scenario"], []).append((src, x))
    summ = {"dataset": DATASET, "entities": len(res), "runs": len(runs), "scenarios": {}}
    for name, items in by.items():
        over = [x for _, x in items if x["days_over"] > 0]
        summ["scenarios"][name] = {"runs": len(items), "runs_with_exceedance": len(over), "resources_with_exceedance": len({s for s, x in items if x["days_over"] > 0}),
                                  "worst_ratio": max(x["max_ratio"] for _, x in items), "median_bound": float(np.median([x["bound"] for _, x in items])),
                                  "median_steps": float(np.median([x["steps"] for _, x in items]))}
    allr = [x for r in res for rr in r["runs"] for x in rr["step_ratios"]]
    allg = [x for r in res for rr in r["runs"] for x in rr["gaps"]]
    summ["promotion"] = {"steps": len(allr), "largest_step_over_allowance": max(allr) if allr else None, "steps_over_allowance": int(sum(x > 1 + 1e-9 for x in allr)),
                         "gap_pairs": len(allg), "shortest_gap_days": min(allg) if allg else None, "gaps_under_14": int(sum(g < 14 for g in allg))}
    (OUT / f"envelope_check_{DATASET}.json").write_text(json.dumps({"summary": summ, "runs": res}))
    print(json.dumps(summ, indent=1))
