"""
Empirical check of the promotion guarantee on development data only.

Claims checked for the proposed design (guard_dual, ledger mode):
  (1) every promotion step moves the live baseline by at most allowance = (allow_base + evidence terms) x unit, unless an
      operator approved (none do in simulation);
  (2) successive promotion steps of one entity are at least shadow_min_days apart.
Run:  python -m evaluation.guarantee_check <nab_dev|cs_dev>
"""
from __future__ import annotations
import json, multiprocessing as mp, os, sys
DATASET = sys.argv[1]
sys.argv = [sys.argv[0], DATASET, "tune"]
os.environ["EVAL_PROFILE"] = "corestack" if DATASET == "cs_dev" else ""
import numpy as np
from pathlib import Path
from evaluation import final_eval as F  # noqa: E402
from evaluation.simulate import run
from phase0.guard import GuardConfig

ROOT = Path(__file__).resolve().parents[1]
CFG = GuardConfig(promotion_mode="ledger")
SC = ("stealth3.0", "stealth2.0", "fast4", "benign")


def one(args):
    idx, e, T, th, prep = args
    if not (prep["stable"] and prep["ambient_free"]):
        return None
    scs = F.scenarios(idx, e)
    out = []
    for name in SC:
        if name not in scs:
            continue
        sc, corro = scs[name]
        kw = F.kwargs_for("dual", "guard_dual", e, T, th)
        r = run(e, sc, "guard_dual", guard_config=CFG, corroborated=corro, **kw)
        unit = r.bounds[1] if r.bounds else None
        out.append({"scenario": name, "unit": unit, "ledger": [{"day": x["day"], "evidence": list(x["evidence"]), "step": float(x["step"]), "capped": bool(x["capped"])} for x in r.ledger]})
    return out


def allowance(ev, unit):
    a = CFG.allow_base
    if "cohort" in ev:
        a += CFG.allow_cohort
    if "change_event" in ev:
        a += CFG.allow_corroborated
    return a * unit


if __name__ == "__main__":
    E = F.build()
    T = F.tuned_block()
    th = F.thresholds(F.frozen()[f"{F.FAMILY}_dev"], 0.05)
    with mp.Pool(2) as pool:
        prep = pool.map(F._prep, [(i, e, T) for i, e in enumerate(E)], chunksize=2)
        runs = [r for r in pool.map(one, [(i, e, T, th, prep[i]) for i, e in enumerate(E)], chunksize=2) if r]
    n_runs = n_steps = viol_step = viol_gap = 0
    ratios, gaps, by_ev = [], [], {}
    for rr in runs:
        for run_ in rr:
            n_runs += 1
            led = sorted(run_["ledger"], key=lambda x: x["day"])
            for x in led:
                if run_["unit"] is None:
                    continue
                n_steps += 1
                a = allowance(x["evidence"], run_["unit"])
                ratio = abs(x["step"]) / a if a else 0.0
                ratios.append(ratio)
                by_ev.setdefault("+".join(x["evidence"]), []).append(ratio)
                viol_step += abs(x["step"]) > a * (1 + 1e-9)
            for p, q in zip(led, led[1:]):
                gaps.append(q["day"] - p["day"])
                viol_gap += (q["day"] - p["day"]) < CFG.shadow_min_days
    res = {"dataset": DATASET, "runs": n_runs, "promotion_steps": n_steps, "step_over_allowance_max": float(max(ratios)) if ratios else None,
           "step_violations": int(viol_step), "gap_pairs": len(gaps), "min_gap_days": float(min(gaps)) if gaps else None,
           "gap_violations": int(viol_gap), "by_evidence_max_ratio": {k: float(max(v)) for k, v in by_ev.items()}, "by_evidence_n": {k: len(v) for k, v in by_ev.items()}}
    (ROOT / f"docs/patent_evaluation/guarantee_check_{DATASET}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
