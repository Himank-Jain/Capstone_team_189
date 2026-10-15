"""
Small-attack sweep: does per-entity calibration earn its place over fixed bounds?
Strategies: adaptive, frozen, guard_default (fixed 1.0/2.0), guard_cal (validated per-entity bounds).
Scenarios: matched no-event control, linear stealth attacks to T in {1,1.5,2,3} sigma over 60 days,
benign growth (draw_scenarios, isolated), adaptive attacker at the bound.
Tuned parameters (margin, cohort stats) are taken from the main run so nothing is re-tuned here.
"""
from __future__ import annotations
import json, multiprocessing as mp, sys
from pathlib import Path
import numpy as np
from evaluation.data import build_entities
from evaluation.runner import eligible
from evaluation.scenarios import EVENT_DAY, Scenario, draw_scenarios
from evaluation.simulate import run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/external/nab_aws_cloudwatch"
TUNED = json.load(open(ROOT / "docs/patent_evaluation/results_raw.json"))["tuned"]
STRATS = ["adaptive", "frozen", "guard_default", "guard_cal"]
TARGETS = [1.0, 1.5, 2.0, 3.0]


def one(args):
    idx, e = args
    cs = TUNED["cohort_stats"]
    kw = {"default_bounds": cs["__global__"]["median_bound"], "margin": TUNED["margin"]}
    kwc = dict(kw, cohort_stats=cs.get(e.group))
    scs = draw_scenarios(idx)
    out = {"id": e.entity_id, "source": e.source, "group": e.group,
           "heldout": e.source not in set(TUNED["tuning_sources"]), "res": {}}
    for s in STRATS:
        k = kwc if s == "guard_cal" else kw
        d = {"control": _s(run(e, scs["control"], s, **k))}
        for T in TARGETS:
            sc = Scenario("attack", "linear", T, ramp_days=60, seed=idx)
            d[f"atk{T}"] = _s(run(e, sc, s, **k))
        d["benign"] = _s(run(e, scs["benign"], s, **k))
        out["res"][s] = d
    out["benign_meta"] = {"magnitude": scs["benign"].magnitude, "cohort": scs["benign"].cohort_fraction > 0}
    return out


def _s(r):
    return {"alerts": sorted(r.alert_days), "inc": sorted(r.incident_days), "bounds": list(r.bounds) if r.bounds else None,
            "drift": r.stored_drift_end}


if __name__ == "__main__":
    E = [e for e in build_entities(DATA, 12) if eligible(e)]
    with mp.Pool(2) as p:
        rows = p.map(one, list(enumerate(E)), chunksize=4)
    Path(ROOT / "docs/patent_evaluation/joint_raw.json").write_text(json.dumps(rows))
    print("done", len(rows))
