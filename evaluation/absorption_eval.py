"""
Rate of baseline absorption after the alert: capped ledger vs unlimited time-based re-baselining vs evidence-only.

Attack = the draw_scenarios attack (ramp 30/60/90 d to 4/6/8 sigma) and the cohort-wide variant.
Variants (all on the calibrated guard):
  full_cohort    existing rule (cohort agreement or operator)
  ledger         evidence-weighted, capped (allow_base 1, cohort +1, change +3 bounds per step)
  ledger_open    same dwell, NO cap: adopt the whole stable shadow (= alert, then re-baseline after the dwell)
Measured: days from first incident until the stored baseline has been displaced by >= 2 / 4 sigma, and the
largest 14-day displacement gain seen (to check the per-window cap).
"""
from __future__ import annotations
import json, multiprocessing as mp, random
from pathlib import Path
import numpy as np
from evaluation.data import build_entities
from evaluation.runner import eligible
from evaluation.scenarios import SNAPSHOT_DAY, draw_scenarios
from evaluation.simulate import run
from phase0.guard import GuardConfig

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/external/nab_aws_cloudwatch"
TUNED = json.load(open(ROOT / "docs/patent_evaluation/results_raw.json"))["tuned"]
P_CHANGE_ATTACK = 0.064
VARIANTS = {
    "full_cohort": GuardConfig(),
    "ledger": GuardConfig(promotion_mode="ledger"),
    "ledger_open": GuardConfig(promotion_mode="ledger", allow_base=1e6, allow_cohort=0.0, allow_corroborated=0.0),
}


def one(args):
    idx, e = args
    cs = TUNED["cohort_stats"]
    kw = {"default_bounds": cs["__global__"]["median_bound"], "margin": TUNED["margin"], "cohort_stats": cs.get(e.group)}
    scs = draw_scenarios(idx)
    ch_a = random.Random(f"ev-{idx}")
    ch_a.random()
    flag = ch_a.random() < P_CHANGE_ATTACK
    out = {"id": e.entity_id, "source": e.source, "heldout": e.source not in set(TUNED["tuning_sources"]),
           "target": scs["attack"].magnitude, "res": {}}
    for v, cfg in VARIANTS.items():
        d = {}
        for name, key in (("attack", "attack"), ("cattack", "cohort_attack")):
            r = run(e, scs[key], "guard_cal", guard_config=cfg, corroborated=flag, **kw)
            d[name] = {"first_inc": min(r.incident_days) if r.incident_days else None,
                       "drift": [round(x, 3) for x in r.drift_daily], "bounds": list(r.bounds) if r.bounds else None,
                       "ledger": [(x["day"], x["step"], x["capped"], x["evidence"]) for x in r.ledger]}
        out["res"][v] = d
    return out


if __name__ == "__main__":
    E = [e for e in build_entities(DATA, 12) if eligible(e)]
    with mp.Pool(2) as p:
        rows = p.map(one, list(enumerate(E)), chunksize=2)
    (ROOT / "docs/patent_evaluation/absorption_raw.json").write_text(json.dumps(rows))
    print("done", len(rows))
