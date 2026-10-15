"""
evaluation/runner.py
====================
Runs the full evaluation grid and aggregates metrics.

Design notes
------------
* Sources are split in two: even-indexed sources *tune* the one free
  parameter of the calibrated guard (the bound margin); results are reported
  only on the other, held-out sources.
* Detection and false-flag comparisons use one common set of entities: those
  whose matched no-event control run stays alert-free from day 60 under every
  compared strategy. That makes strategies comparable on identical entities
  and removes ambient alerts from the attack/benign comparison.
"""

from __future__ import annotations

import multiprocessing as mp
import statistics
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from evaluation.data import Entity, build_entities
from evaluation.scenarios import END_DAY, EVENT_DAY, adaptive_attack, draw_scenarios
from evaluation.simulate import run
from phase0.guard.calibration import MIN_BOUND

STRATEGIES = [
    "adaptive", "frozen", "longwin", "clip", "cusum", "rollback",
    "guard_default", "guard_naive", "guard_cal", "guard_b1", "guard_b2", "guard_b3",
]
COMPARE = ["adaptive", "frozen", "longwin", "clip", "cusum", "rollback", "guard_cal"]
ADAPTIVE_STRATEGIES = ["adaptive", "frozen", "guard_default", "guard_cal"]
PAYLOADS = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0]
MIN_SCALE_OVER_STD = 0.05
MARGIN_QUANTILE = 0.90


def eligible(entity: Entity) -> bool:
    std = float(np.std(entity.values[: 30 * 24])) + 1e-12
    return entity.hour_scale / std >= MIN_SCALE_OVER_STD


def _summ(r) -> dict:
    return {
        "alerts": sorted(r.alert_days),
        "incidents": sorted(r.incident_days),
        "holds": len(r.hold_days),
        "collapsed": len(r.collapsed_days),
        "promoted": r.promoted_buckets,
        "promo_days": r.promotion_days,
        "drift": r.stored_drift_end,
        "bounds": list(r.bounds) if r.bounds else None,
        "bound_src": r.bound_source,
        "checks": {k: (list(v) if isinstance(v, tuple) else v) for k, v in r.calib_checks.items()},
    }


# ---- pass 1 ------------------------------------------------------------------

def _pass1(args):
    entity, scenario = args
    r = run(entity, scenario["control"], "guard_probe")
    t = r.traces or {}
    t = dict(t)
    t["flag_days"] = sorted(r.flag_days)
    return entity.entity_id, entity.group, entity.source, t


def tune_and_cohorts(entities: List[Entity], pool) -> dict:
    sources = sorted({e.source for e in entities})
    tuning_sources = set(sources[::2])
    jobs = [(e, draw_scenarios(i)) for i, e in enumerate(entities)]
    outs = pool.map(_pass1, jobs)
    ratios = []
    usable = []
    for eid, group, source, t in outs:
        if len(t.get("d_c", [])) < 20 or "later_c" not in t:
            continue
        usable.append((eid, group, source, t))
        if source in tuning_sources:
            p99_c = float(np.percentile(t["d_c"], 99)) + 1e-9
            p99_w = float(np.percentile(t["d_w"], 99)) + 1e-9
            ratios.append(max(t["later_c"] / p99_c, t["later_w"] / p99_w))
    margin = max(1.25, float(np.quantile(ratios, MARGIN_QUANTILE))) if ratios else 1.25
    by_group: Dict[str, List[tuple]] = {}
    for item in usable:
        by_group.setdefault(item[1], []).append(item)
    stats: Dict[str, dict] = {}
    raw_all = []
    for group, items in by_group.items():
        all_w = np.concatenate([np.asarray(t["d_w"]) for _, _, _, t in items])
        all_c = np.concatenate([np.asarray(t["d_c"]) for _, _, _, t in items])
        raw = [(max(MIN_BOUND, margin * float(np.percentile(t["d_w"], 99))), max(MIN_BOUND, margin * float(np.percentile(t["d_c"], 99))))
               for _, _, _, t in items]
        raw_all.extend(raw)
        stats[group] = {
            "p95": (float(np.percentile(all_w, 95)), float(np.percentile(all_c, 95))),
            "median_bound": (float(np.median([b[0] for b in raw])), float(np.median([b[1] for b in raw]))),
            "n": len(items),
        }
    stats["__global__"] = {
        "median_bound": (float(np.median([b[0] for b in raw_all])), float(np.median([b[1] for b in raw_all]))),
        "n": len(raw_all),
    }
    return {
        "margin": margin, "tuning_sources": sorted(tuning_sources),
        "n_tuning_entities": len(ratios),
        "ratio_quantiles": {str(q): float(np.quantile(ratios, q)) for q in (0.5, 0.75, 0.9, 0.95)} if ratios else {},
        "cohort_stats": stats,
    }


# ---- pass 2 ------------------------------------------------------------------

def _grid(args):
    idx, entity, tuned = args
    cohort_stats = tuned["cohort_stats"]
    margin = tuned["margin"]
    scs = draw_scenarios(idx)
    cs = cohort_stats.get(entity.group)
    dflt = cohort_stats["__global__"]["median_bound"]
    heldout = entity.source not in set(tuned["tuning_sources"])
    out: dict = {
        "id": entity.entity_id, "group": entity.group, "source": entity.source, "heldout": heldout,
        "scen": {}, "adaptive": {},
        "benign_meta": {"cohort": scs["benign"].cohort_fraction > 0, "magnitude": scs["benign"].magnitude,
                        "temporary": scs["benign"].temporary},
        "attack_meta": {"profile": scs["attack"].profile, "target": scs["attack"].magnitude,
                        "ramp": scs["attack"].ramp_days},
        "poison_meta": {"ramp": scs["poisoned_cal"].ramp_days, "target": scs["poisoned_cal"].magnitude},
    }
    kw_cal = {"cohort_stats": cs, "default_bounds": dflt, "margin": margin}
    kw = {"default_bounds": dflt, "margin": margin}
    for strat in STRATEGIES:
        k = kw_cal if strat == "guard_cal" else kw
        out["scen"][strat] = {name: _summ(run(entity, sc, strat, **k)) for name, sc in scs.items()}
    out["unvalidated"] = {
        "control": _summ(run(entity, scs["control"], "guard_cal", validate_calibration=False, **kw_cal)),
        "poisoned_cal": _summ(run(entity, scs["poisoned_cal"], "guard_cal", validate_calibration=False, **kw_cal)),
    }
    out["operator_benign"] = _summ(run(entity, scs["benign"], "guard_cal", operator_approves=True, **kw_cal))

    cal = out["scen"]["guard_cal"]["control"]["bounds"]
    c_bound = cal[1] if cal else dflt[1]
    ramp = 0.9 * c_bound
    for strat in ADAPTIVE_STRATEGIES:
        k = kw_cal if strat == "guard_cal" else kw
        res = {"ramp_level": ramp, "payloads": {}}
        for pay in PAYLOADS:
            sc = adaptive_attack(ramp, max(pay, ramp), seed=idx)
            res["payloads"][str(pay)] = _summ(run(entity, sc, strat, **k))
        out["adaptive"][strat] = res
    return out


def run_grid(replicas: int, data_dir: Path, workers: int = 2, limit: Optional[int] = None) -> dict:
    t0 = time.time()
    entities = [e for e in build_entities(data_dir, replicas) if eligible(e)]
    if limit:
        entities = entities[:limit]
    excluded = sorted({e.source for e in build_entities(data_dir, 1) if not eligible(e)})
    with mp.Pool(workers) as pool:
        tuned = tune_and_cohorts(entities, pool)
        rows = pool.map(_grid, [(i, e, tuned) for i, e in enumerate(entities)], chunksize=2)
    return {
        "n_entities": len(entities),
        "sources": sorted({e.source for e in entities}),
        "excluded_sources": excluded,
        "tuned": tuned,
        "rows": rows,
        "elapsed_s": time.time() - t0,
    }


# ---- aggregation -------------------------------------------------------------------

def _any_in(days: List[int], lo: int, hi: int = END_DAY) -> bool:
    return any(lo <= d < hi for d in days)


def _wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return [round(100 * max(0.0, (c - h) / d), 1), round(100 * min(1.0, (c + h) / d), 1)]


def _prop(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": _wilson(k, n)}


def _med(xs):
    return statistics.median(xs) if xs else None


def aggregate(result: dict) -> dict:
    rows = [r for r in result["rows"] if r["heldout"]]
    quiet_all = [r for r in rows if all(not _any_in(r["scen"][s]["control"]["alerts"], EVENT_DAY) for s in COMPARE)]
    agg: dict = {
        "heldout_entities": len(rows), "common_quiet_entities": len(quiet_all),
        "margin": result["tuned"]["margin"], "tuning_sources": result["tuned"]["tuning_sources"],
        "n_tuning_entities": result["tuned"]["n_tuning_entities"],
        "ratio_quantiles": result["tuned"]["ratio_quantiles"],
        "strategies": {},
    }
    for strat in STRATEGIES:
        s: dict = {}
        ctrl = sum(_any_in(r["scen"][strat]["control"]["alerts"], EVENT_DAY) for r in rows)
        s["control_alert"] = _prop(ctrl, len(rows))
        # false incidents: guard only
        # attack
        det = 0
        by_ramp = {}
        drift, ttd = [], []
        for r in quiet_all:
            a = r["scen"][strat]["attack"]
            ramp = r["attack_meta"]["ramp"]
            hit = _any_in(a["alerts"], EVENT_DAY, EVENT_DAY + ramp + 30)
            det += hit
            by = by_ramp.setdefault(str(ramp), [0, 0])
            by[0] += hit
            by[1] += 1
            drift.append(a["drift"])
            if hit:
                ttd.append(min(d for d in a["alerts"] if d >= EVENT_DAY) - EVENT_DAY)
        s["attack"] = {
            **_prop(det, len(quiet_all)),
            "by_ramp": {k: _prop(*v) for k, v in sorted(by_ramp.items(), key=lambda kv: int(kv[0]))},
            "median_stored_drift_at_ramp_end": _med(drift),
            "median_days_to_first_alert": _med(ttd),
        }
        # benign
        k = 0
        alert_days = []
        for r in quiet_all:
            b = r["scen"][strat]["benign"]
            k += _any_in(b["alerts"], EVENT_DAY)
            alert_days.append(sum(1 for d in b["alerts"] if d >= EVENT_DAY))
        s["benign"] = {**_prop(k, len(quiet_all)), "median_alert_days": _med(alert_days)}
        # poisoned calibration, cohort attack
        for name in ("poisoned_cal", "cohort_attack"):
            kk = sum(_any_in(r["scen"][strat][name]["alerts"], EVENT_DAY) for r in quiet_all)
            s[name] = {**_prop(kk, len(quiet_all)),
                       "median_stored_drift": _med([r["scen"][strat][name]["drift"] for r in quiet_all])}
        agg["strategies"][strat] = s

    # calibration validation arm (guard_cal validated vs unvalidated), common quiet + unvalidated quiet
    qa = [r for r in quiet_all if not _any_in(r["unvalidated"]["control"]["alerts"], EVENT_DAY)]
    agg["calibration_validation"] = {
        "n": len(qa),
        "validated_detected": _prop(sum(_any_in(r["scen"]["guard_cal"]["poisoned_cal"]["alerts"], EVENT_DAY) for r in qa), len(qa)),
        "unvalidated_detected": _prop(sum(_any_in(r["unvalidated"]["poisoned_cal"]["alerts"], EVENT_DAY) for r in qa), len(qa)),
        "validated_median_stored_drift": _med([r["scen"]["guard_cal"]["poisoned_cal"]["drift"] for r in qa]),
        "unvalidated_median_stored_drift": _med([r["unvalidated"]["poisoned_cal"]["drift"] for r in qa]),
        "validated_rejected_calibration": sum(
            r["scen"]["guard_cal"]["poisoned_cal"]["checks"].get("result") not in ("ok", None) for r in rows),
        "poisoned_runs": len(rows),
    }
    srcs: Dict[str, int] = {}
    reasons: Dict[str, int] = {}
    wb, cb = [], []
    for r in rows:
        c = r["scen"]["guard_cal"]["control"]
        srcs[c["bound_src"]] = srcs.get(c["bound_src"], 0) + 1
        reasons[c["checks"].get("result", "?")] = reasons.get(c["checks"].get("result", "?"), 0) + 1
        if c["bounds"]:
            wb.append(c["bounds"][0])
            cb.append(c["bounds"][1])
    agg["calibrated_bounds"] = {
        "sources": srcs, "validation_results": reasons,
        "median_windowed": _med(wb), "median_cumulative": _med(cb),
        "p10_cumulative": float(np.percentile(cb, 10)) if cb else None,
        "p90_cumulative": float(np.percentile(cb, 90)) if cb else None,
    }
    agg["default_bounds"] = result["tuned"]["cohort_stats"]["__global__"]["median_bound"]

    def bucket(items):
        incidents = [x for x in items if x["incidents"]]
        promoted = [x for x in incidents if x["promoted"]]
        lags = [min(x["promo_days"]) - min(x["incidents"]) for x in promoted if x["promo_days"]]
        return {
            "runs": len(items), "with_incident": len(incidents), "promoted": len(promoted),
            "median_days_incident_to_promotion": _med(lags),
            "median_incidents_per_run": _med([len(x["incidents"]) for x in incidents]),
            "median_collapsed_alert_days": _med([x["collapsed"] for x in incidents]),
        }

    g = [(r, r["scen"]["guard_cal"]) for r in rows]
    agg["promotion"] = {
        "benign_cohort_wide": bucket([c["benign"] for r, c in g if r["benign_meta"]["cohort"]]),
        "benign_isolated": bucket([c["benign"] for r, c in g if not r["benign_meta"]["cohort"]]),
        "benign_isolated_operator": bucket([r["operator_benign"] for r, c in g if not r["benign_meta"]["cohort"]]),
        "attack_isolated": bucket([c["attack"] for r, c in g]),
        "attack_cohort_wide": bucket([c["cohort_attack"] for r, c in g]),
    }
    mags = [(0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.01)]
    by_mag = {}
    for strat in ("adaptive", "frozen", "guard_cal", "guard_b3"):
        out = []
        for lo, hi in mags:
            sel = [r for r in quiet_all if lo <= r["benign_meta"]["magnitude"] < hi]
            kk = sum(_any_in(r["scen"][strat]["benign"]["alerts"], EVENT_DAY) for r in sel)
            out.append({"range": f"{lo:g}-{min(hi, 4):g}", **_prop(kk, len(sel))})
        by_mag[strat] = out
    agg["benign_by_magnitude"] = by_mag

    ada = {}
    for strat in ADAPTIVE_STRATEGIES:
        per = {}
        for pay in PAYLOADS:
            ev = sum(not _any_in(r["adaptive"][strat]["payloads"][str(pay)]["alerts"], EVENT_DAY) for r in quiet_all)
            per[str(pay)] = _prop(ev, len(quiet_all))
        ada[strat] = per
    agg["adaptive_attacker_evasion"] = ada
    agg["adaptive_ramp_level_median"] = _med([r["adaptive"]["guard_cal"]["ramp_level"] for r in quiet_all])
    return agg
