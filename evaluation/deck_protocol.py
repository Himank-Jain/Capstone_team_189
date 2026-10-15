"""
Replication of the evaluation protocol described by the target deck (Dr. Giri's "Unified" proposal), on real CoreStack series.

    python -m evaluation.deck_protocol <dataset> fleet     per-entity self-calibration (clean and poisoned calibration), cached
    python -m evaluation.deck_protocol <dataset> eval      every strategy on every scenario

Protocol (docs/patent_evaluation/PREREG_DECK_PROTOCOL.md fixes it before the held-out run)
  entities    CoreStack series that pass evaluation.runner.eligible; headline population = STABLE, AMBIENT-FREE and NOT FLAT series
              (flat = no variation at all before the event; reported separately)
  drift       linear, stepped and noise-masked, 30 days, from the event day.  Two readings of "0.5% to 3% per day, scaled to
              each entity's variance":
                R1  daily rate 0.5/1/2/3 % of the entity's own hour-scale unit, i.e. a 30-day total of 0.15/0.3/0.6/0.9 units
                R2  daily rate 0.5/1/2/3 % of the entity's own mean level, additive
              every entity gets each of the three profiles once, with the rate assigned by (index + profile index) mod 4
  comparators adaptive (reference), 2x window, 5x slower (150-reading window = a cumulative mean on 90-day series),
              robust median/MAD, slower + robust, the guard (bound trigger), the guard with the sequential trigger
  metrics     displacement of the stored baseline after the drift; share detected within the drift (alert for a baseline,
              incident for the guard); median detection delay; false-flag rate on permanent benign level shifts
  stress      adaptive attacker that ramps to 95 % of the entity's cumulative bound and then jumps to a 3-unit payload;
              attacker present during calibration, with and without the validation checks
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys

DATASET = sys.argv[1]
STAGE = sys.argv[2] if len(sys.argv) > 2 else "eval"
sys.argv = ["x", DATASET, "none"]  # final_eval reads argv at import

import numpy as np  # noqa: E402

from evaluation.final_eval import EV, OUT, ZCLIP, _prep, build  # noqa: E402
from evaluation.margin_rule import selfcal  # noqa: E402
from evaluation.scenarios import BOUNDS_DAY, END_DAY, Scenario, apply_scenario  # noqa: E402
from evaluation.simulate import run  # noqa: E402
from phase0.guard import GuardConfig  # noqa: E402
from phase0.guard.calibration import MIN_BOUND  # noqa: E402

ALPHA, B = 0.05, 80
LEDGER_FREEZE = GuardConfig(promotion_mode="ledger", freeze_on_hold=True)
TRIG = json.load(open(OUT / "frozen_trigger.json"))  # {"src","floor","w","k","q","m"}: fixed on development data only
PROFILES = ("linear", "stepped", "noise_masked")
R1_TOTAL = (0.15, 0.30, 0.60, 0.90)
R2_RATE = (0.005, 0.01, 0.02, 0.03)
R3_TOTAL = (1.0, 2.0, 3.0, 4.0)  # R3: the 30-day ramp family of the earlier stealth tests, totals in hour-scale units
BENIGN = (0.25, 0.5, 1.0, 2.0, 3.0)
PAYLOAD = 3.0
PAYLOAD_SMALL = 1.0  # second payload size, fixed in advance: what a stealthier payload does to each strategy
RIVALS = ("adaptive", "w2x", "slow5", "robust", "slow5_robust")


def trig_kwargs():
    return {"trig_src": TRIG["src"], "trig_floor": TRIG["floor"], "trig_k": TRIG["k"], "trig_w": TRIG["w"]}


def threshold(cal):
    """Global constant in standardised units. A per-entity threshold from resampled clean futures was tried on development
    data and was no better (and unreachable for the trimmed summary): see PREREG_DECK_PROTOCOL.md."""
    return TRIG["c"]


def scenario_set(idx, bc):
    sc = {"control": Scenario("control")}
    for pi, p in enumerate(PROFILES):
        sc[f"R1_{p}"] = Scenario("attack", p, R1_TOTAL[(idx + pi) % 4], ramp_days=30, seed=idx)
        sc[f"R2_{p}"] = Scenario("attack", p, 30 * R2_RATE[(idx + pi + 1) % 4], ramp_days=30, seed=idx, unit="level")
        sc[f"R3_{p}"] = Scenario("attack", p, R3_TOTAL[(idx + pi + 2) % 4], ramp_days=30, seed=idx)
    sc["benign"] = Scenario("benign", "linear", BENIGN[idx % 5], ramp_days=7, seed=idx)
    # a permanent shift of half the entity's own calibrated cumulative bound: inside what the guard is built to tolerate
    sc["benign_sub"] = Scenario("benign", "linear", 0.5 * max(bc, MIN_BOUND), ramp_days=7, seed=idx)
    sc["adaptive_attacker"] = Scenario("adaptive", "linear", 0.95 * max(bc, MIN_BOUND), ramp_days=20, payload=PAYLOAD, seed=idx)
    sc["adaptive_attacker_1"] = Scenario("adaptive", "linear", 0.95 * max(bc, MIN_BOUND), ramp_days=20, payload=PAYLOAD_SMALL, seed=idx)
    sc["poisoned"] = Scenario("poisoned_cal", "linear", 3.0, start=35, ramp_days=25, seed=idx)
    return sc


def _fleet(args):
    idx, e = args
    cal = selfcal(e, e.values, B, ALPHA, seed=idx)
    r = run(e, Scenario("control"), "guard_probe")
    t = r.traces or {}
    pois = selfcal(e, apply_scenario(e, Scenario("poisoned_cal", "linear", 3.0, start=35, ramp_days=25, seed=idx)), B, ALPHA, seed=10_000 + idx)
    return {"idx": idx, "cal": cal, "pois": pois, "n_dc": len(t.get("d_c", []))}


def _row(r, strat):
    spec = sorted(r.incident_days) if strat.startswith("guard") else sorted(r.alert_days)
    return {"spec": spec, "alerts": sorted(r.alert_days), "first": (min(x for x in spec if x >= EV) if any(x >= EV for x in spec) else None),
            "drift_final": r.stored_drift_final, "drift_max": max(r.drift_daily) if r.drift_daily else 0.0,
            "held_end": (END_DAY - 1) in r.held_end_days, "held_days": len(r.held_end_days), "flag_days": sorted(r.flag_days),
            "collapsed": sorted(r.collapsed_days), "promotions": sorted(r.promotion_days), "steps": len(r.ledger or []),
            "bounds": r.bounds, "bound_source": r.bound_source, "calib": r.calib_checks.get("result"),
            "cusum_days": sorted(r.cusum_days)}


def _eval_one(args):
    idx, e, cal, pois, gdef, meta = args
    out = {"id": e.entity_id, "source": e.source, "group": e.group, **meta, "bc": cal["bc"], "bw": cal["bw"], "h": threshold(cal),
           "flat": bool(float(np.std(e.values[: BOUNDS_DAY * 24])) == 0.0), "res": {}}
    scs = scenario_set(idx, cal["bc"])
    tk = trig_kwargs()
    for name, sc in scs.items():
        cl = pois if sc.kind == "poisoned_cal" else cal
        d = {}
        for strat in RIVALS:
            d[strat] = _row(run(e, sc, strat), strat)
        gkw = {"default_bounds": gdef, "cohort_stats": None, "guard_config": LEDGER_FREEZE, "raw_bounds": (cl["bw"], cl["bc"])}
        d["guard"] = _row(run(e, sc, "guard_cal", **gkw), "guard")
        d["guard_trig"] = _row(run(e, sc, "guard_dual", cusum_h=threshold(cl), zclip=ZCLIP, **gkw, **tk), "guard_trig")
        if sc.kind == "poisoned_cal":  # the same attacker, but the calibration is used as computed (no alert exclusion, trend check, fallback)
            d["guard_unvalidated"] = _row(run(e, sc, "guard_cal", validate_calibration=False, **gkw), "guard_unvalidated")
        out["res"][name] = d
    return out


if __name__ == "__main__":
    E = build()
    print(DATASET, STAGE, "entities", len(E), "series", len({e.source for e in E}), "trigger", TRIG, flush=True)
    cache = OUT / f"deckproto_fleet_{DATASET}.json"
    with mp.Pool(2) as pool:
        prep = pool.map(_prep, [(i, e, None) for i, e in enumerate(E)], chunksize=2)
        if cache.exists():
            fleet = json.load(open(cache))
        else:
            fleet = pool.map(_fleet, [(i, e) for i, e in enumerate(E)], chunksize=1)
            cache.write_text(json.dumps(fleet))
        if STAGE == "fleet":
            print("fleet done", len(fleet))
            sys.exit(0)
        raw = [(max(MIN_BOUND, f["cal"]["bw"]), max(MIN_BOUND, f["cal"]["bc"])) for f in fleet if f["n_dc"] >= 20]
        gdef = (float(np.median([b[0] for b in raw])), float(np.median([b[1] for b in raw])))
        print("fleet default bound (median of the dataset's own entities)", gdef, flush=True)
        rows = pool.map(_eval_one, [(i, E[i], fleet[i]["cal"], fleet[i]["pois"], gdef, prep[i]) for i in range(len(E))], chunksize=1)
    (OUT / f"deckproto_{DATASET}.json").write_text(json.dumps({"trigger": TRIG, "default_bound": gdef, "rows": rows}))
    print("done", len(rows))
