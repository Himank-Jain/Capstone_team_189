"""
Component ablation and allowance sweep for the self-calibrated governed baseline.

    python -m evaluation.ablation_eval <dataset> eval          # ABL_SET=ablation (default) | curve | curve_ev0

Every variant uses the frozen self-calibrated bound (evaluation/margin_rule.py, cached by selfcal_eval); the only things
that change between variants are which of the claimed parts are switched on:

  adaptive        no guard: the production rolling baseline
  H               claim 1 alone: validated bound + hold, no promotion path (a held entity stays held)
  S               claim 2 alone: shadow baseline + stability-gated capped ledgered promotion, triggered by a sequential
                  detector (robust CUSUM, threshold tuned on development data) because no displacement bound exists;
                  the allowance is a fixed 1 scale unit per step; no calibration validation
  HS_unlinked     both, but the allowance is a fixed 1 scale unit and not derived from the validated bound
  HS_unvalidated  both, bound used as computed, no alert exclusion / trend check / default fallback
  HS_nocap        both, with the cap removed: the stable shadow is adopted in full (ledger still written)
  full            both, allowance = 1 validated bound per step, ledger records the validation outcome (the design)
  full_B          the same with the original partial hold instead of freeze-on-hold (as run on fresh2)

The allowance sweep (ABL_SET=curve) varies the allowance of the full design: allow_base in multiples of the validated bound
(linked) and fixed_unit in scale units (unlinked), plus the two ends (hold only; no cap).
curve_ev0 is the same sweep with change-event corroboration forced off (the stable shadow alone justifies the step).
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
from dataclasses import replace

from evaluation.final_eval import (DATASET, EV, FAMILY, OUT, ZCLIP, _prep, _s, build, frozen, scenarios, thresholds)
from evaluation.lit_attacks import lit_scenarios
from evaluation.margin_rule import selfcal
from evaluation.scenarios import END_DAY, SNAPSHOT_DAY, apply_scenario
from evaluation.selfcal_eval import ALPHA, B, FLEET_CACHE, LEDGER_FREEZE, POISONED_CACHE, cohort_stats
from evaluation.simulate import run
from phase0.guard import GuardConfig

SET = os.environ.get("ABL_SET", "ablation")
TS = tuple(t for t in (14, 30, 60, 100) if EV + t < END_DAY)  # days after the event at which the state is read
FIXED_UNIT = 1.0  # scale units; the unlinked allowance used by S and HS_unlinked
LEDGER = GuardConfig(promotion_mode="ledger")


def _cal_kw(cal, CS):
    return {"default_bounds": CS["__global__"]["median_bound"], "cohort_stats": None, "raw_bounds": (cal["bw"], cal["bc"])}


def _plain(cal, CS, th):
    return _cal_kw(cal, CS)


def _unvalidated(cal, CS, th):
    return {**_cal_kw(cal, CS), "validate_calibration": False}


def _trigger_only(cal, CS, th):
    # no displacement bound, no validation: the sequential detector is the only trigger
    return {"default_bounds": CS["__global__"]["median_bound"], "cohort_stats": None, "cusum_h": th["full"], "zclip": ZCLIP,
            "validate_calibration": False}


# label -> (strategy, guard config, spec label, kwargs builder)
ABLATION = {
    "adaptive": ("adaptive", None, "adaptive", lambda cal, CS, th: {}),
    "H": ("guard_cal", replace(LEDGER_FREEZE, promotion_mode="none"), "cal_ledger", _plain),
    "S": ("guard_full", replace(LEDGER_FREEZE, fixed_unit=FIXED_UNIT), "full", _trigger_only),
    "HS_unlinked": ("guard_cal", replace(LEDGER_FREEZE, fixed_unit=FIXED_UNIT), "cal_ledger", _plain),
    "HS_unvalidated": ("guard_cal", LEDGER_FREEZE, "cal_ledger", _unvalidated),
    "HS_nocap": ("guard_cal", replace(LEDGER_FREEZE, allow_base=1e6), "cal_ledger", _plain),
    "full": ("guard_cal", LEDGER_FREEZE, "cal_ledger", _plain),
    "full_B": ("guard_cal", LEDGER, "cal_ledger", _plain),
}
ALLOW_LINKED = (0.5, 1.0, 2.0, 4.0, 8.0, 16.0)
ALLOW_FIXED = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
CURVE = {"hold_only": ABLATION["H"], "no_cap": ABLATION["HS_nocap"]}
for k in ALLOW_LINKED:
    CURVE[f"L{k:g}"] = ("guard_cal", replace(LEDGER_FREEZE, allow_base=k), "cal_ledger", _plain)
for u in ALLOW_FIXED:
    CURVE[f"F{u:g}"] = ("guard_cal", replace(LEDGER_FREEZE, fixed_unit=u), "cal_ledger", _plain)

VARIANTS = ABLATION if SET == "ablation" else CURVE
CURVE_SCEN = ("control", "stealth2.0", "stealth3.0", "fast4", "benign", "greedy", "frog1.15")


def _scenarios(idx, e):
    scs = dict(scenarios(idx, e))
    for name, sc in lit_scenarios(idx).items():
        scs[name] = (sc, None)
    if SET != "ablation":
        scs = {k: v for k, v in scs.items() if k in CURVE_SCEN}
    if SET == "curve_ev0":
        scs = {k: (sc, (False if corro is not None else None)) for k, (sc, corro) in scs.items()}
    return scs


def _run_one(args):
    idx, e, CS, clean_cal, meta, pois_cal, th = args
    out = {"id": e.entity_id, "source": e.source, "group": e.group, **meta, "res": {}}
    scs = _scenarios(idx, e)
    out["benign_mag"] = scs["benign"][0].magnitude if "benign" in scs else None
    cals = {}
    for lab, (strat, cfg, spec_lab, kwf) in VARIANTS.items():
        d = {}
        for name, (sc, corro) in scs.items():
            if sc.kind == "poisoned_cal":
                if "poisoned" not in cals:
                    cals["poisoned"] = pois_cal or selfcal(e, apply_scenario(e, sc), B, ALPHA, seed=10_000 + idx)
                cal = cals["poisoned"]
            else:
                cal = clean_cal
            kw = kwf(cal, CS, th)
            if cfg is not None:
                kw["guard_config"] = cfg
                if corro is not None:
                    kw["corroborated"] = corro
            r = run(e, sc, strat, **kw)
            row = _s(spec_lab, r)
            row["goal_day"] = r.goal_day
            row["max_drift"] = max(r.drift_daily) if r.drift_daily else 0.0
            row["promotions"] = len(r.promotion_days)
            row["unit_sources"] = sorted({x.get("unit_source") for x in (r.ledger or [])})
            row["validation"] = sorted({str(x.get("validation")) for x in (r.ledger or [])})
            row["bound_source"] = r.bound_source
            dd = r.drift_daily  # stored displacement at the end of each day from SNAPSHOT_DAY on
            row["drift_at"] = {str(t): (dd[EV + t - SNAPSHOT_DAY] if 0 <= EV + t - SNAPSHOT_DAY < len(dd) else None) for t in TS}
            row["t15"] = next((i + SNAPSHOT_DAY - EV for i, v in enumerate(dd) if i + SNAPSHOT_DAY >= EV and v >= 1.5), None)
            held = set(r.held_end_days)
            row["unres_at"] = {str(t): bool((EV + t) in held or any(EV + t - 14 < x <= EV + t for x in row["spec"])) for t in TS}
            row["flag_by"] = {str(t): any(EV <= x <= EV + t for x in row["spec"]) for t in TS}
            d[name] = row
        out["res"][lab] = d
    return out


if __name__ == "__main__":
    E = build()
    th = thresholds(frozen()[f"{FAMILY}_dev"], float(os.environ.get("FPR_TARGET", "0.05")))
    fleet = json.load(open(FLEET_CACHE))
    CS = cohort_stats(fleet)
    pc = json.load(open(POISONED_CACHE)) if POISONED_CACHE.exists() else {}
    print(DATASET, SET, "entities", len(E), "series", len({e.source for e in E}), "variants", list(VARIANTS), "S trigger h", th["full"], flush=True)
    with mp.Pool(2) as pool:
        prep = pool.map(_prep, [(i, e, None) for i, e in enumerate(E)], chunksize=2)
        rows = pool.map(_run_one, [(i, E[i], CS, fleet[i]["cal"], prep[i], pc.get(str(i)), th) for i in range(len(E))], chunksize=1)
    (OUT / f"ablation_{SET}_{DATASET}.json").write_text(json.dumps({"thresholds": th, "fixed_unit": FIXED_UNIT, "rows": rows}))
    print("done", len(rows))
