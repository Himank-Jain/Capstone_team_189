"""
Label-free rule for the displacement bound (replaces the per-dataset margin m).

    python -m evaluation.margin_rule <nab_dev|cs_dev> [B] [alpha...]

Rule ("self-calibrated bound").  At BOUNDS_DAY, for one entity:
  1. take the validated calibration days [SNAPSHOT_DAY, BOUNDS_DAY) of the entity's own series;
  2. build B synthetic series of the same length as the deployment horizon, in which every day after the snapshot is drawn
     with replacement from those calibration days of the same day type (weekday / weekend), and run the unmodified baseline
     process on each (no attack, no hold);
  3. the bound is the (1 - alpha) quantile, over the B replicates, of the largest displacement from the trusted snapshot seen
     after BOUNDS_DAY (cumulative and windowed separately).
Inputs are the entity's own unlabelled history, the deployment horizon and alpha (a per-entity false-hold target).  No other
dataset, no attack data and no tuned multiplier is used.

This module only measures how well that bound covers the REAL future displacement of clean entities (development data).
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
from dataclasses import replace

import numpy as np

DATASET = sys.argv[1] if len(sys.argv) > 1 else "cs_dev"
os.environ.setdefault("EVAL_PROFILE", {"cs_dev": "corestack", "cs_fresh": "corestack90", "cs_fresh2": "corestack90"}.get(DATASET, ""))
from evaluation.data import SIM_START  # noqa: E402
from evaluation.scenarios import BOUNDS_DAY, END_DAY, SNAPSHOT_DAY, Scenario  # noqa: E402
from evaluation.simulate import run  # noqa: E402


def resampled_series(values: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Training days unchanged; every later day is a calibration day of the same type drawn with replacement."""
    n_days = END_DAY
    out = np.array(values[: n_days * 24], dtype=float, copy=True)
    pool = {0: [], 1: []}
    for d in range(SNAPSHOT_DAY, BOUNDS_DAY):
        pool[int((SIM_START.weekday() + d) % 7 >= 5)].append(d)
    for d in range(SNAPSHOT_DAY, n_days):
        wk = int((SIM_START.weekday() + d) % 7 >= 5)
        src = int(rng.choice(pool[wk]))
        out[d * 24:(d + 1) * 24] = values[src * 24:(src + 1) * 24]
    return out


def future_max_samples(entity, B: int, seed: int = 0):
    """Largest cumulative and windowed displacement after BOUNDS_DAY in B resampled clean futures."""
    rng = np.random.default_rng(seed)
    wc, ww = [], []
    for _ in range(B):
        v = resampled_series(entity.values, rng)
        r = run(entity, Scenario("control"), "guard_probe", series=v)
        t = r.traces
        wc.append(t.get("later_c", 0.0))
        ww.append(t.get("later_w", 0.0))
    return np.array(wc), np.array(ww)


def self_calibrated_bound(entity, B: int = 40, alpha: float = 0.10, seed: int = 0):
    wc, ww = future_max_samples(entity, B, seed)
    return float(np.quantile(ww, 1 - alpha)), float(np.quantile(wc, 1 - alpha))


ZCLIP = 3.0  # residual clip of the sequential trigger (a fixed design constant, identical for every dataset)
H_MIN = 3.0  # the sequential trigger never fires below this level (smallest value of the grid used for the tuned design)


def selfcal(entity, values: np.ndarray, B: int = 80, alpha: float = 0.05, seed: int = 0) -> dict:
    """Self-calibrated operating point for one entity from its own calibration days (see module docstring).

    alpha is the target probability of a false hold per entity over the horizon, split evenly between the displacement
    bound and the sequential trigger; within the bound it is split again between its windowed and cumulative parts."""
    rng = np.random.default_rng(seed)
    wc, ww, hh = [], [], []
    for _ in range(B):
        r = run(entity, Scenario("control"), "guard_dualprobe", series=resampled_series(values, rng), zclip=ZCLIP, cusum_h=1e18)
        wc.append(r.traces.get("later_c", 0.0))
        ww.append(r.traces.get("later_w", 0.0))
        hh.append(r.max_cusum)
    qb, qh = 1 - alpha / 4, 1 - alpha / 2
    return {"bw": float(np.quantile(ww, qb, method="higher")), "bc": float(np.quantile(wc, qb, method="higher")),
            "h": max(H_MIN, float(np.quantile(hh, qh, method="higher"))), "B": B, "alpha": alpha}


def _one(args):
    idx, e, B, alphas = args
    r = run(e, Scenario("control"), "guard_probe")
    t = r.traces
    if len(t.get("d_c", [])) < 20 or "later_c" not in t:
        return None
    wc, ww = future_max_samples(e, B, seed=idx)
    from evaluation.final_eval import label
    stable, ms = label(e)
    out = {"idx": idx, "id": e.entity_id, "source": e.source, "group": e.group, "stable": stable, "max_shift": ms,
           "p99_c": float(np.percentile(t["d_c"], 99)), "p99_w": float(np.percentile(t["d_w"], 99)),
           "later_c": float(t["later_c"]), "later_w": float(t["later_w"]),
           "boot_c": {str(a): float(np.quantile(wc, 1 - a)) for a in alphas},
           "boot_w": {str(a): float(np.quantile(ww, 1 - a)) for a in alphas}}
    return out


if __name__ == "__main__":
    from evaluation.final_eval import build, tuned_block, label
    B = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    alphas = [float(a) for a in sys.argv[3:]] or [0.05, 0.10]
    E = build()
    T = tuned_block()
    print(DATASET, "entities", len(E), "B", B, "alphas", alphas, flush=True)
    with mp.Pool(2) as pool:
        rows = [r for r in pool.map(_one, [(i, e, B, alphas) for i, e in enumerate(E)], chunksize=1) if r]
    json.dump({"dataset": DATASET, "B": B, "alphas": alphas, "margin_tuned": T["margin"], "rows": rows},
              open(f"/tmp/claude-0/-home-claude/5a37d6c9-c9b4-53d2-85d8-fb414890be8c/scratchpad/margin_rule_{DATASET}.json", "w"))
    print("rows", len(rows))
