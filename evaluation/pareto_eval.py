"""
Joint outcome across every comparator: what can an attacker displace the baseline by before anyone is told
(silent displacement at the first alert), against what a legitimate shift costs (alert burden, whether it resolves).

Strategies: the six comparators, the guard with fleet-median bounds, the calibrated guard with the existing
cohort promotion rule ("full"), and the calibrated guard with the evidence-weighted ledger.
Evidence rates come from real CoreStack data (see ledger_eval.py).
"""
from __future__ import annotations
import json, multiprocessing as mp, random
from pathlib import Path
from evaluation.data import build_entities
from evaluation.runner import eligible
from evaluation.scenarios import END_DAY, Scenario, draw_scenarios
from evaluation.simulate import run
from phase0.guard import GuardConfig

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/external/nab_aws_cloudwatch"
TUNED = json.load(open(ROOT / "docs/patent_evaluation/results_raw.json"))["tuned"]
P_CHANGE_BENIGN, P_CHANGE_ATTACK = 0.20, 0.064
TAIL = 14

# label -> (simulate strategy, guard config)
CONFIGS = {
    "adaptive": ("adaptive", None), "frozen": ("frozen", None), "longwin": ("longwin", None),
    "clip": ("clip", None), "cusum": ("cusum", None), "rollback": ("rollback", None),
    "guard_fleet": ("guard_default", GuardConfig()),
    "guard_cal_full": ("guard_cal", GuardConfig()),
    "guard_cal_ledger": ("guard_cal", GuardConfig(promotion_mode="ledger")),
}


def _s(r):
    held = sorted(r.held_end_days)
    return {"alerts": sorted(r.alert_days), "inc": sorted(r.incident_days),
            "first_alert_drift": r.first_alert_drift, "first_alert_day": r.first_alert_day,
            "tail_alert": any(d >= END_DAY - TAIL for d in r.alert_days),
            "tail_held": (END_DAY - 1) in r.held_end_days, "held_days": len(held),
            "drift_final": r.stored_drift_final}


def one(args):
    idx, e = args
    cs = TUNED["cohort_stats"]
    scs = draw_scenarios(idx)
    rng = random.Random(f"ev-{idx}")
    ch_b = rng.random() < P_CHANGE_BENIGN
    ch_a = rng.random() < P_CHANGE_ATTACK
    iso = Scenario("benign", "linear", scs["benign"].magnitude, ramp_days=7, cohort_fraction=0.0,
                   temporary=scs["benign"].temporary, seed=scs["benign"].seed)
    scen = {"control": (scs["control"], None), "attack": (scs["attack"], ch_a), "benign_iso": (iso, ch_b)}
    for T in (1.0, 2.0):
        scen[f"stealth{T}"] = (Scenario("attack", "linear", T, ramp_days=60, seed=idx), ch_a)
    out = {"id": e.entity_id, "source": e.source, "heldout": e.source not in set(TUNED["tuning_sources"]),
           "meta": {"benign_mag": iso.magnitude, "benign_change": ch_b, "attack_target": scs["attack"].magnitude,
                    "attack_ramp": scs["attack"].ramp_days}, "res": {}}
    for label, (strat, cfg) in CONFIGS.items():
        kw = {"default_bounds": cs["__global__"]["median_bound"], "margin": TUNED["margin"]}
        if strat == "guard_cal":
            kw["cohort_stats"] = cs.get(e.group)
        d = {}
        for name, (sc, corro) in scen.items():
            extra = {}
            if cfg is not None:
                extra["guard_config"] = cfg
                if corro is not None:
                    extra["corroborated"] = corro
            d[name] = _s(run(e, sc, strat, **kw, **extra))
        out["res"][label] = d
    return out


if __name__ == "__main__":
    E = [e for e in build_entities(DATA, 12) if eligible(e)]
    with mp.Pool(2) as p:
        rows = p.map(one, list(enumerate(E)), chunksize=2)
    (ROOT / "docs/patent_evaluation/pareto_raw.json").write_text(json.dumps(rows))
    print("done", len(rows))
