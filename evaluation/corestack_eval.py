"""
Guard evaluation on REAL CoreStack telemetry (independent of NAB).

Entities are real hourly series (100 contiguous days, Monday-aligned) from CoreStack's Azure metrics.
Timeline is compressed: snapshot day 30, calibration 30-59, bounds/event day 60, end day 100.
Splits are by RESOURCE: even-indexed resources tune the bound margin, odd-indexed resources are reported.
Scenarios: control (real data only: natural behaviour, including real level shifts), injected stealth
ramps, injected attacks, poisoned calibration. n is reported in resources as well as series.
Run with:  EVAL_PROFILE=corestack python -m evaluation.corestack_eval
"""
from __future__ import annotations
import json, multiprocessing as mp, os
from pathlib import Path
import numpy as np

assert os.environ.get("EVAL_PROFILE") == "corestack", "set EVAL_PROFILE=corestack"
from evaluation.corestack import load_series
from evaluation.data import Entity, _bucket_scales, _residual_scale
from evaluation.runner import tune_and_cohorts, eligible
from evaluation.scenarios import BOUNDS_DAY, END_DAY, EVENT_DAY, Scenario
from evaluation.simulate import run

ROOT = Path(__file__).resolve().parents[1]
STRATS = ["adaptive", "frozen", "longwin", "clip", "cusum", "rollback", "guard_default", "guard_naive", "guard_cal"]


def build():
    S = load_series("corestack_series_100d.pkl")
    ents = []
    for (rid, metric, cat), rec in sorted(S.items()):
        v = np.asarray(rec["values"], float)
        if len(v) < END_DAY * 24:
            continue
        v = v[: END_DAY * 24]
        ents.append(Entity(entity_id=f"{rid.split('/')[-1]}|{metric}", source=rid.lower(), group=f"{cat}:{metric}",
                           replica=0, values=v, hour_scale=_residual_scale(v[: 30 * 24]),
                           bucket_scale=_bucket_scales(v[: 30 * 24])))
    return [e for e in ents if eligible(e)]


def _s(r):
    return {"alerts": sorted(r.alert_days), "inc": sorted(r.incident_days), "bounds": list(r.bounds) if r.bounds else None,
            "src": r.bound_source, "checks": {k: (list(x) if isinstance(x, tuple) else x) for k, x in r.calib_checks.items()},
            "drift": r.stored_drift_end, "fdrift": r.stored_drift_final, "first_alert_drift": r.first_alert_drift}


def one(args):
    idx, e, tuned = args
    cs = tuned["cohort_stats"]
    kw = {"default_bounds": cs["__global__"]["median_bound"], "margin": tuned["margin"]}
    scs = {"control": Scenario("control")}
    for ramp in (10, 20, 30):
        for T in (2.0, 3.0, 4.0):
            scs[f"atk_r{ramp}_t{T}"] = Scenario("attack", "linear", T, ramp_days=ramp, seed=idx)
    scs["poisoned"] = Scenario("poisoned_cal", "linear", 3.0, start=35, ramp_days=25, seed=idx)
    out = {"id": e.entity_id, "resource": e.source, "group": e.group, "heldout": e.source not in set(tuned["tuning_sources"]), "res": {}}
    for s in STRATS:
        k = dict(kw, cohort_stats=cs.get(e.group)) if s == "guard_cal" else kw
        out["res"][s] = {n: _s(run(e, sc, s, **k)) for n, sc in scs.items()}
    out["res"]["guard_unvalidated"] = {n: _s(run(e, scs[n], "guard_cal", validate_calibration=False, cohort_stats=cs.get(e.group), **kw))
                                       for n in ("control", "poisoned")}
    return out


if __name__ == "__main__":
    E = build()
    print("entities", len(E), "resources", len({e.source for e in E}), flush=True)
    with mp.Pool(2) as pool:
        tuned = tune_and_cohorts(E, pool)
        print("margin", tuned["margin"], "tuning resources", len(tuned["tuning_sources"]), flush=True)
        rows = pool.map(one, [(i, e, tuned) for i, e in enumerate(E)], chunksize=2)
    (ROOT / "docs/patent_evaluation/corestack_eval_raw.json").write_text(json.dumps({"tuned": tuned, "rows": rows}))
    print("done", len(rows))
