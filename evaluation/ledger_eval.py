"""
Evidence-weighted promotion ledger vs the existing promotion rules, on the calibrated guard.

Evidence is simulated at the rates measured on real CoreStack data (docs/patent_evaluation/CORESTACK.md):
  change event present for a benign shift  : 0.20  (sensitivity)
  change event present for a data-plane attack: 0.064 (false-anchor rate)
Cohort evidence follows the scenario (cohort-wide benign / cohort-wide attack = 0.9 agreement, isolated = 0).
Cohort agreement is NOT discriminating on real data, so the cohort-wide attack is the worst case.
"""
from __future__ import annotations
import json, multiprocessing as mp, random
from pathlib import Path
import numpy as np
from evaluation.data import build_entities
from evaluation.runner import eligible
from evaluation.scenarios import EVENT_DAY, END_DAY, Scenario, draw_scenarios
from evaluation.simulate import run
from phase0.guard import GuardConfig

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/external/nab_aws_cloudwatch"
TUNED = json.load(open(ROOT / "docs/patent_evaluation/results_raw.json"))["tuned"]
P_CHANGE_BENIGN, P_CHANGE_ATTACK = 0.20, 0.064

VARIANTS = {
    "full_cohort": GuardConfig(),
    "full_corroborated": GuardConfig(promotion_rule="corroborated"),
    "ledger": GuardConfig(promotion_mode="ledger"),
    "ledger_strict": GuardConfig(promotion_mode="ledger", allow_base=0.5, allow_cohort=0.5, allow_corroborated=2.0),
    "ledger_loose": GuardConfig(promotion_mode="ledger", allow_base=2.0, allow_cohort=2.0, allow_corroborated=6.0),
}


def _summ(r):
    inc = sorted(r.incident_days)
    held = sorted(r.held_end_days)
    still = (END_DAY - 1) in r.held_end_days
    return {"inc": inc, "first_inc": inc[0] if inc else None, "held_days": len(held),
            "resolved_day": None if still or not held else held[-1] + 1,
            "still_held": still, "alerts": sorted(r.alert_days), "drift_final": r.stored_drift_final,
            "drift_probe": r.stored_drift_end, "promos": r.promotion_days,
            "steps": [(round(x["day"] - r.promotion_days[0] if r.promotion_days else 0, 1), x["capped"], x["evidence"]) for x in r.ledger][:12] if r.ledger else []}


def one(args):
    idx, e = args
    cs = TUNED["cohort_stats"]
    kw = {"default_bounds": cs["__global__"]["median_bound"], "margin": TUNED["margin"], "cohort_stats": cs.get(e.group)}
    scs = draw_scenarios(idx)
    rng = random.Random(f"ev-{idx}")
    ch_b = rng.random() < P_CHANGE_BENIGN
    ch_a = rng.random() < P_CHANGE_ATTACK
    ch_c = rng.random() < P_CHANGE_ATTACK
    out = {"id": e.entity_id, "source": e.source, "heldout": e.source not in set(TUNED["tuning_sources"]),
           "benign_meta": {"mag": scs["benign"].magnitude, "cohort": scs["benign"].cohort_fraction > 0,
                           "temp": scs["benign"].temporary, "change": ch_b},
           "attack_meta": {"target": scs["attack"].magnitude, "ramp": scs["attack"].ramp_days, "change": ch_a},
           "cattack_meta": {"change": ch_c}, "res": {}}
    iso = Scenario("benign", "linear", scs["benign"].magnitude, ramp_days=7, cohort_fraction=0.0,
                   temporary=scs["benign"].temporary, seed=scs["benign"].seed)
    for name, cfg in VARIANTS.items():
        d = {}
        d["control"] = _summ(run(e, scs["control"], "guard_cal", guard_config=cfg, **kw))
        d["benign"] = _summ(run(e, scs["benign"], "guard_cal", guard_config=cfg, corroborated=ch_b, **kw))
        d["benign_iso"] = _summ(run(e, iso, "guard_cal", guard_config=cfg, corroborated=ch_b, **kw))
        d["benign_iso_op"] = _summ(run(e, iso, "guard_cal", guard_config=cfg, corroborated=ch_b, operator_approves=True, **kw))
        d["attack"] = _summ(run(e, scs["attack"], "guard_cal", guard_config=cfg, corroborated=ch_a, **kw))
        d["cattack"] = _summ(run(e, scs["cohort_attack"], "guard_cal", guard_config=cfg, corroborated=ch_c, **kw))
        out["res"][name] = d
    return out


if __name__ == "__main__":
    E = [e for e in build_entities(DATA, 12) if eligible(e)]
    with mp.Pool(2) as p:
        rows = p.map(one, list(enumerate(E)), chunksize=2)
    (ROOT / "docs/patent_evaluation/ledger_raw.json").write_text(json.dumps(rows))
    print("done", len(rows))
