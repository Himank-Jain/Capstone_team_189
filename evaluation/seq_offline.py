"""
Offline comparison of sequential triggers on the daily residual series written by evaluation/xbar_collect.py.

A trigger sees, for one entity, the daily mean residual x_t of its readings against the trusted snapshot.
Days SNAPSHOT_DAY..BOUNDS_DAY-1 are the validated calibration days (reference); monitoring starts at BOUNDS_DAY.

Label-free calibration of a trigger's threshold, per entity (no attack data, no labels, no other entity):
  1. B synthetic clean futures: every monitored day is drawn, with replacement, from the entity's own calibration days
     of the same day type (or, for the block null, a block of consecutive calibration days from the same weekday);
  2. the statistic's largest value over the monitored horizon in each future;
  3. threshold = the q-quantile of those maxima.
Because the statistic of a future day only depends on that day's own readings and the snapshot, drawing x values is the
same as drawing whole days and re-running the pipeline (what evaluation/margin_rule.py does, 100x slower).
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np

from evaluation.data import SIM_START

OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"
ZCLIP = 3.0
SD_FLOOR = 0.05


def load(dataset):
    d = json.load(open(OUT / f"xbar_{dataset}.json"))
    x = {int(k): {s: np.asarray(v, float) for s, v in r.items()} for k, r in d["x"].items()}
    return d, x


def daytype(n_days, snapshot_day, wk0=0):
    return np.array([int((SIM_START + timedelta(days=snapshot_day + j + wk0)).weekday() >= 5) for j in range(n_days)])


def reference(x, ncal, floor=SD_FLOOR):
    ref = x[:ncal]
    return float(np.mean(ref)), max(float(np.std(ref)), floor)


# ---- statistics (each returns the running statistic per monitored day, shape (..., T)) -------------------------------

def cusum_path(z, k=0.5):
    """Two-sided CUSUM, max of the two sides, along the last axis. z has shape (..., T)."""
    z = np.asarray(z, float)
    sp = np.zeros(z.shape[:-1]); sn = np.zeros(z.shape[:-1])
    out = np.empty_like(z)
    for t in range(z.shape[-1]):
        sp = np.maximum(0.0, sp + z[..., t] - k)
        sn = np.maximum(0.0, sn - z[..., t] - k)
        out[..., t] = np.maximum(sp, sn)
    return out


def window_path(z, w=14):
    """sqrt(w) * |mean of the last w standardised days| (a moving-average detector); first w-1 days use what is there."""
    z = np.asarray(z, float)
    out = np.empty_like(z)
    cs = np.cumsum(z, axis=-1)
    for t in range(z.shape[-1]):
        n = min(w, t + 1)
        s = cs[..., t] - (cs[..., t - n] if t - n >= 0 else 0.0)
        out[..., t] = np.sqrt(n) * np.abs(s) / n
    return out


def trend_path(z, w=21):
    """|OLS slope| over the last w days times the span (the shift the line implies over the window), in sd units,
    divided by its standard error under independent noise: a ramp detector. Needs at least 7 days."""
    z = np.asarray(z, float)
    out = np.zeros_like(z)
    for t in range(z.shape[-1]):
        n = min(w, t + 1)
        if n < 7:
            continue
        seg = z[..., t - n + 1: t + 1]
        tt = np.arange(n) - (n - 1) / 2.0
        sxx = float(np.sum(tt * tt))
        slope = np.sum(seg * tt, axis=-1) / sxx
        out[..., t] = np.abs(slope) * np.sqrt(sxx)
    return out


DETECTORS = {
    "cusum0.5": lambda z: cusum_path(z, 0.5),
    "cusum0.25": lambda z: cusum_path(z, 0.25),
    "cusum1.0": lambda z: cusum_path(z, 1.0),
    "win7": lambda z: window_path(z, 7),
    "win14": lambda z: window_path(z, 14),
    "trend21": lambda z: trend_path(z, 21),
    "trend14": lambda z: trend_path(z, 14),
}


def standardise(xm, mu, sd):
    return np.clip((xm - mu) / sd, -ZCLIP, ZCLIP)


# ---- the null ------------------------------------------------------------------------------------------------------

def null_futures(xcal, dtype_all, ncal, T, B, rng, block=1):
    """B clean futures of length T (monitored days). block=1: iid day draw by day type. block=7: moving blocks of 7
    consecutive calibration days that begin on the same weekday as the position they fill."""
    out = np.empty((B, T))
    pos_dt = dtype_all[ncal: ncal + T]
    if block == 1:
        pools = {0: np.where(dtype_all[:ncal] == 0)[0], 1: np.where(dtype_all[:ncal] == 1)[0]}
        for t in range(T):
            p = pools[int(pos_dt[t])]
            out[:, t] = xcal[rng.choice(p, size=B)]
        return out
    # weekday of calibration day j and of future position t
    wd = np.arange(len(dtype_all)) % 7  # relative weekday index; only equalities matter
    for b in range(B):
        t = 0
        while t < T:
            # choose a start so that weekday matches: candidate cal starts s with (s - (ncal + t)) % 7 == 0, s + block <= ncal
            cands = [s for s in range(0, ncal - block + 1) if (s - (ncal + t)) % 7 == 0]
            if not cands:
                cands = list(range(0, max(1, ncal - block + 1)))
            s = cands[rng.integers(len(cands))]
            for u in range(block):
                if t >= T:
                    break
                out[b, t] = xcal[min(s + u, ncal - 1)]
                t += 1
    return out
