"""
Frozen-design evaluation harness.

    python -m evaluation.final_eval <dataset> tune     sweep each tunable threshold on DEVELOPMENT data, control runs only,
                                                        and freeze the smallest threshold whose false-alert rate on
                                                        stable, ambient-free entities is <= the target
    python -m evaluation.final_eval <dataset> eval     run every strategy on every scenario with the frozen thresholds

datasets   nab_dev     AWS CloudWatch series used throughout development (day-resampled, synthetic ordering)
           nab_fresh   NAB series of other categories, never run before (tweets, ad exchange, known-cause)
           cs_dev      CoreStack 100-day series used throughout development
           cs_fresh    CoreStack resources present only in the 90-day extract, never run before

Thresholds are tuned on *_dev only. *_fresh is run once with the frozen file docs/patent_evaluation/frozen_design.json.
Truth labels never come from a detector: a CoreStack entity is STABLE if its own data stays within 1 hour-scale unit of
its reference level (evaluation/stable.py); NAB entities are stationary by construction apart from injected scenarios.
An entity is AMBIENT-FREE if the plain adaptive baseline raises no ordinary z-flag after the event day, so that
strategy-specific alerts can be isolated.  Alerts counted:  CUSUM -> CUSUM alarms;  guards -> incidents;  other
comparators -> their own z-flag alerts.
"""
from __future__ import annotations
import json, multiprocessing as mp, os, random, sys
from pathlib import Path

DATASET, STAGE = sys.argv[1], sys.argv[2]
os.environ["EVAL_PROFILE"] = {"cs_dev": "corestack", "cs_fresh": "corestack90", "cs_fresh2": "corestack90", "cs_fresh3": "corestack90", "cs_long": "corestack_long"}.get(DATASET, "")
import numpy as np
from evaluation.data import Entity, _bucket_scales, _residual_scale, build_entities
from evaluation.runner import eligible
from evaluation.scenarios import BOUNDS_DAY, END_DAY, EVENT_DAY, SNAPSHOT_DAY, Scenario
from evaluation.simulate import run
from evaluation.stable import max_shift
from phase0.guard import GuardConfig

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/patent_evaluation"
FROZEN = OUT / "frozen_design.json"
FAMILY = "cs" if DATASET.startswith("cs") else "nab"
EV = EVENT_DAY
LONG_RAMP = 20 if FAMILY == "cs" else 60
P_CHANGE_BENIGN, P_CHANGE_ATTACK = 0.20, 0.064  # control-plane change-event rates measured on real CoreStack data
H_GRID = [3.0, 5.0, 8.0, 12.0, 18.0, 30.0, 50.0, 80.0, 120.0, 200.0]
M_GRID = [2.0, 3.0, 4.5, 7.0, 10.0, 15.0, 25.0, 40.0]
S_GRID = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0]
TARGETS_FPR = (0.05, 0.10)
STABLE_SHIFT = 1.0


def _cs_long(dev):
    """Development resources, first 60 real days; every later day to day 200 is a calibration day (days 30-59) of the same
    weekday type drawn with replacement (the 'clean future' construction of evaluation/margin_rule.py, one fixed draw per
    series). Synthetic order: it tests the long-horizon behaviour of the mechanism, not real long-horizon behaviour."""
    import zlib
    from evaluation.data import SIM_START
    ents = []
    for (rid, metric, cat), rec in sorted(dev.items()):
        v = np.asarray(rec["values"], float)
        if len(v) < 100 * 24:
            continue
        rng = np.random.default_rng(zlib.crc32(f"{rid}|{metric}".encode()))
        out = np.empty(END_DAY * 24)
        out[: BOUNDS_DAY * 24] = v[: BOUNDS_DAY * 24]
        pool = {0: [], 1: []}
        for d in range(SNAPSHOT_DAY, BOUNDS_DAY):
            pool[int((SIM_START.weekday() + d) % 7 >= 5)].append(d)
        for d in range(BOUNDS_DAY, END_DAY):
            src = int(rng.choice(pool[int((SIM_START.weekday() + d) % 7 >= 5)]))
            out[d * 24:(d + 1) * 24] = v[src * 24:(src + 1) * 24]
        ents.append(Entity(entity_id=f"{rid.split('/')[-1]}|{metric}", source=rid.lower(), group=f"{cat}:{metric}", replica=0,
                           values=out, hour_scale=_residual_scale(out[: 30 * 24]), bucket_scale=_bucket_scales(out[: 30 * 24])))
    return [e for e in ents if eligible(e)]


def _wk0(rec) -> int:
    """Weekday of the series' first day (Monday = 0). Every set before cs_fresh3 starts on a Monday."""
    import datetime as _dt
    return _dt.date.fromisoformat(rec["start"]).weekday() if DATASET == "cs_fresh3" and rec.get("start") else 0


def build():
    if DATASET == "nab_dev":
        return [e for e in build_entities(ROOT / "data/external/nab_aws_cloudwatch", 12) if eligible(e)]
    if DATASET == "nab_fresh":
        return [e for e in build_entities(ROOT / "data/external/nab_fresh", 3) if eligible(e)]
    from evaluation.corestack import load_series
    dev = load_series("corestack_series_100d.pkl")
    if DATASET == "cs_long":
        return _cs_long(dev)
    if DATASET == "cs_dev":
        S, days = dev, 100
    elif DATASET == "cs_fresh2":  # resources outside both earlier sets; rule in scripts/build_corestack_fresh2.py
        S, days = load_series("corestack_series_fresh2_90d.pkl"), 90
    elif DATASET == "cs_fresh3":  # resources outside dev, fresh and fresh2; same rule, scripts/build_corestack_fresh2.py FRESH3=1
        S, days = load_series("corestack_series_fresh3_90d.pkl"), 90
    else:
        used = {k[0] for k in dev}
        S = {k: v for k, v in load_series("corestack_series_90d.pkl").items() if k[0] not in used}
        days = 90
    ents = []
    for (rid, metric, cat), rec in sorted(S.items()):
        v = np.asarray(rec["values"], float)
        if len(v) < days * 24:
            continue
        v = v[: days * 24]
        wk0 = _wk0(rec)
        ents.append(Entity(entity_id=f"{rid.split('/')[-1]}|{metric}", source=rid.lower(), group=f"{cat}:{metric}", replica=0,
                           values=v, hour_scale=_residual_scale(v[: 30 * 24], wk0), bucket_scale=_bucket_scales(v[: 30 * 24], wk0), wk0=wk0))
    return [e for e in ents if eligible(e)]


def frozen():
    return json.load(open(FROZEN)) if FROZEN.exists() else {}


def tuned_block():
    """Margin, cohort statistics and tuning sources fixed during development (never recomputed on fresh data)."""
    if FAMILY == "nab":
        return json.load(open(OUT / "results_raw.json"))["tuned"]
    return json.load(open(OUT / "corestack_eval_raw.json"))["tuned"]


def label(e):
    """Strategy-independent truth: stable = no 14-day window beyond STABLE_SHIFT hour-scale units after the event day."""
    if FAMILY == "nab":
        return True, 0.0
    ms = max_shift(e.values, e.hour_scale, BOUNDS_DAY, EVENT_DAY, getattr(e, 'wk0', 0))
    return bool(ms < STABLE_SHIFT), float(ms)


def scenarios(idx, e):
    rng = random.Random(f"final-{DATASET}-{idx}")
    ch_b, ch_a = rng.random() < P_CHANGE_BENIGN, rng.random() < P_CHANGE_ATTACK
    sc = {"control": (Scenario("control"), None)}
    for T in (1.0, 2.0, 3.0):
        sc[f"stealth{T}"] = (Scenario("attack", "linear", T, ramp_days=LONG_RAMP, seed=idx), ch_a)
    sc["fast4"] = (Scenario("attack", "linear", 4.0, ramp_days=10, seed=idx), ch_a)
    sc["local4"] = (Scenario("attack", "linear", 4.0, ramp_days=LONG_RAMP, hours=tuple(range(8, 16)), seed=idx), ch_a)
    sc["poisoned"] = (Scenario("poisoned_cal", "linear", 3.0, start=35, ramp_days=25 if FAMILY == "cs" else 90, seed=idx), ch_a)
    mag = rng.uniform(0.5, 4.0)
    sc["benign"] = (Scenario("benign", "linear", mag, ramp_days=7, temporary=rng.random() < 0.25, seed=idx), ch_b)
    return sc


ZCLIP = 3.0  # outlier clip on the daily standardised residual, applied to every robust CUSUM variant
F_GRID = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]  # floor of the calibrated per-entity bound, in scale units

# label -> (simulate strategy, GuardConfig or None, threshold keys it takes)
LEDGER = GuardConfig(promotion_mode="ledger")
CONFIGS = {
    "adaptive": ("adaptive", None, ()), "frozen": ("frozen", None, ()), "longwin": ("longwin", None, ()),
    "clip": ("clip", None, ()), "rollback": ("rollback", None, ()),
    "cusum": ("cusum", None, ("cusum",)),
    "cusum_r": ("cusum_r", None, ("cusum_r",)),
    "guard_fleet": ("guard_default", GuardConfig(), ("s",)),
    "guard_cal": ("guard_cal", GuardConfig(), ("f",)),                 # validated calibration, bounds trigger, old promotion rule
    "cal_ledger": ("guard_cal", LEDGER, ("f",)),                        # validated calibration + ledger (lead claim as first written)
    "full_noledger": ("guard_full", GuardConfig(), ("full",)),          # robust CUSUM trigger + validated reference, old promotion
    "full": ("guard_full", LEDGER, ("full",)),                          # robust CUSUM trigger + validated reference + ledger
    "dual_noledger": ("guard_dual", GuardConfig(), ("dual_h", "dual_f")),
    "dual": ("guard_dual", LEDGER, ("dual_h", "dual_f")),               # bounds trigger + robust CUSUM trigger + validated + ledger
}


def spec(label_, r):
    if label_ in ("cusum", "cusum_r"):
        return sorted(r.cusum_days)
    if label_.startswith(("guard", "cal", "full", "dual")):
        return sorted(r.incident_days)
    return sorted(r.alert_days)


def kwargs_for(label_, strat, e, T, th):
    cs = T["cohort_stats"]
    base = cs["__global__"]["median_bound"]
    kw = {"default_bounds": base, "margin": T["margin"]}
    if strat in ("guard_cal", "guard_full", "guard_dual"):
        kw["cohort_stats"] = cs.get(e.group)
    if label_ == "cusum":
        kw["cusum_h"] = th.get("cusum", 12.0)
    if label_ == "cusum_r":
        kw.update(cusum_h=th.get("cusum_r", 12.0), zclip=ZCLIP)
    if strat == "guard_full":
        kw.update(cusum_h=th.get("full", 12.0), zclip=ZCLIP)
    if strat == "guard_dual":
        kw.update(cusum_h=th.get("dual_h", 12.0), zclip=ZCLIP)
        if th.get("dual_f") is not None:
            kw["floor"] = th["dual_f"]
    if strat == "guard_cal" and th.get("f") is not None:
        kw["floor"] = th["f"]
    if label_ == "guard_fleet":
        s = th.get("s", 1.0)
        kw["default_bounds"] = (base[0] * s, base[1] * s)
    return kw


def _prep(args):
    idx, e, T = args
    stable, ms = label(e)
    amb = run(e, Scenario("control"), "adaptive")
    return {"idx": idx, "stable": stable, "max_shift": ms, "ambient_free": not any(d >= EV for d in amb.flag_days)}


def _tune_one(args):
    idx, e, T = args
    out = {"idx": idx, "fpr": {}}
    sc = Scenario("control")
    for h in H_GRID:
        r = run(e, sc, "cusum", **kwargs_for("cusum", "cusum", e, T, {"cusum": h}))
        out["fpr"][f"cusum_{h}"] = any(d >= EV for d in r.cusum_days)
        r = run(e, sc, "cusum_r", **kwargs_for("cusum_r", "cusum_r", e, T, {"cusum_r": h}))
        out["fpr"][f"cusum_r_{h}"] = any(d >= EV for d in r.cusum_days)
        kw = kwargs_for("full", "guard_full", e, T, {"full": h})
        r = run(e, sc, "guard_full", guard_config=LEDGER, **kw)
        out["fpr"][f"full_{h}"] = any(d >= EV for d in r.incident_days)
    for f in F_GRID:
        r = run(e, sc, "guard_cal", guard_config=GuardConfig(), **kwargs_for("guard_cal", "guard_cal", e, T, {"f": f}))
        out["fpr"][f"f_{f}"] = any(d >= EV for d in r.incident_days)
    for s_ in S_GRID:
        r = run(e, sc, "guard_default", **kwargs_for("guard_fleet", "guard_default", e, T, {"s": s_}))
        out["fpr"][f"s_{s_}"] = any(d >= EV for d in r.incident_days)
    return out


def _post_gain(r, lag=14):
    """Largest rise of the stored baseline's displacement over any `lag`-day window that starts at or after the first alert."""
    if r.first_alert_day is None or not r.drift_daily:
        return None
    off = r.first_alert_day - SNAPSHOT_DAY
    d = r.drift_daily
    best = 0.0
    for i in range(max(off, 0), len(d) - lag):
        best = max(best, d[i + lag] - d[i])
    return best


def _s(label_, r):
    held = sorted(r.held_end_days)
    return {"spec": spec(label_, r), "alerts": sorted(r.alert_days), "first_alert_drift": r.first_alert_drift,
            "first_alert_day": r.first_alert_day, "tail_alert": any(d >= END_DAY - 14 for d in spec(label_, r)),
            "tail_held": (END_DAY - 1) in r.held_end_days, "held_days": len(held), "drift_final": r.stored_drift_final,
            "calib": r.calib_checks.get("result"), "ref": r.calib_checks.get("trigger_reference"),
            "post_gain14": _post_gain(r), "unit": (r.bounds[1] if r.bounds else None),
            "steps": len(r.ledger) if r.ledger else 0, "capped_steps": sum(1 for x in (r.ledger or []) if x.get("capped"))}


def _eval_one(args):
    idx, e, T, th, meta = args
    out = {"id": e.entity_id, "source": e.source, "group": e.group, **meta, "res": {}}
    scs = scenarios(idx, e)
    out["benign_mag"] = scs["benign"][0].magnitude
    for lab, (strat, cfg, _keys) in CONFIGS.items():
        d = {}
        for name, (sc, corro) in scs.items():
            kw = kwargs_for(lab, strat, e, T, th)
            if cfg is not None:
                kw["guard_config"] = cfg
                if corro is not None:
                    kw["corroborated"] = corro
            d[name] = _s(lab, run(e, sc, strat, **kw))
        out["res"][lab] = d
    return out


def pick(table, grid, target):
    meet = [g for g in grid if table[str(g)] <= target]
    return min(meet) if meet else None


def table_of(prep, tune, grid, prefix):
    ok = {r["idx"] for r in prep if r["stable"] and r["ambient_free"]}
    t = [r for r in tune if r["idx"] in ok]
    return {str(g): sum(r["fpr"][f"{prefix}_{g}"] for r in t) / max(len(t), 1) for g in grid}, len(t)


FAMS = (("cusum", H_GRID), ("cusum_r", H_GRID), ("full", H_GRID), ("f", F_GRID), ("s", S_GRID))


def thresholds(block, target):
    """Frozen operating points. Single-trigger methods get the whole false-alert budget; the dual trigger splits it in half."""
    tb, th, unreachable = block["tables"], {}, []
    for fam, grid in FAMS:
        v = pick(tb[fam], grid, target)
        if v is None:
            v, _ = grid[-1], unreachable.append(fam)
        th[fam] = v
    for key, fam, grid in (("dual_h", "full", H_GRID), ("dual_f", "f", F_GRID)):
        v = pick(tb[fam], grid, target / 2)
        if v is None:
            v, _ = grid[-1], unreachable.append(key)
        th[key] = v
    th["unreachable"] = unreachable
    return th


if __name__ == "__main__":
    E = build()
    T = tuned_block()
    print(DATASET, STAGE, "entities", len(E), "series", len({e.source for e in E}), flush=True)
    with mp.Pool(2) as pool:
        prep = pool.map(_prep, [(i, e, T) for i, e in enumerate(E)], chunksize=2)
        if STAGE == "tune":
            tune = pool.map(_tune_one, [(i, e, T) for i, e in enumerate(E)], chunksize=2)
            design = frozen()
            blk = {"n_entities": len(E), "n_sources": len({e.source for e in E}), "tables": {}}
            for fam, grid in FAMS:
                blk["tables"][fam], n = table_of(prep, tune, grid, fam)
            blk["n_stable_ambient_free"] = n
            design[DATASET] = blk
            FROZEN.write_text(json.dumps(design, indent=1))
            for t in TARGETS_FPR:
                print(t, thresholds(blk, t))
        else:
            target = float(os.environ.get("FPR_TARGET", "0.05"))
            th = thresholds(frozen()[f"{FAMILY}_dev"], target)
            print("frozen thresholds at target", target, th, flush=True)
            rows = pool.map(_eval_one, [(i, e, T, th, prep[i]) for i, e in enumerate(E)], chunksize=2)
            (OUT / f"final_{DATASET}_{target}.json").write_text(json.dumps({"thresholds": th, "rows": rows}))
            print("done", len(rows))
