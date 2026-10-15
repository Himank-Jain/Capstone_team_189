"""
Do real, sustained level shifts in CoreStack telemetry line up with control-plane
change events on the same resource?

Shift: day t is a shift onset if the median daily level over days [t, t+7) differs
from the median over [t-14, t) by >= 3 robust scale units AND the following week
[t+7, t+14) stays on the same side (sustained). Scale = 1.4826*MAD of the prior 14
daily values, floored at 5% of the series' overall median absolute level.
Aligned: a change event on the same resource within +/-3 days of onset.
Null: the same number of onsets placed uniformly at random on the same series.
Negative control: read-type operations (listKeys) should align no more than the null.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from evaluation.corestack import daily_medians, load_events, load_series

WIN = 3
rng = np.random.default_rng(0)


def onsets(m: np.ndarray):
    out, t = [], 14
    floor = 0.05 * (np.median(np.abs(m)) + 1e-9)
    while t <= len(m) - 14:
        prior = m[t - 14:t]
        scale = max(1.4826 * np.median(np.abs(prior - np.median(prior))), floor, 1e-9)
        a, b = np.median(m[t:t + 7]) - np.median(prior), np.median(m[t + 7:t + 14]) - np.median(prior)
        if abs(a) >= 3 * scale and abs(b) >= 3 * scale and np.sign(a) == np.sign(b):
            out.append(t)
            t += 14
        else:
            t += 1
    return out


def aligned(day: dt.date, evs) -> bool:
    return any(abs((e - day).days) <= WIN for e in evs)


def main():
    S = load_series()
    E = load_events()
    per_res = defaultdict(lambda: {"n": 0, "obs": {"change": 0, "read": 0, "any": 0}, "null": {"change": 0, "read": 0, "any": 0}})
    tot = {"n": 0, "series": 0, "series_with_onset": 0}
    for key, rec in S.items():
        rid = key[0].lower()
        ev = E.get(rid)
        if ev is None:
            continue
        m = daily_medians(rec["values"])
        start = dt.date.fromisoformat(rec["start"])
        ons = onsets(m)
        tot["series"] += 1
        if not ons:
            continue
        tot["series_with_onset"] += 1
        r = per_res[rid]
        for t in ons:
            r["n"] += 1
            tot["n"] += 1
            for kind in ("change", "read", "any"):
                r["obs"][kind] += aligned(start + dt.timedelta(days=t), ev[kind])
        # null: 200 random placements per onset
        for _ in range(len(ons)):
            for rep in range(200):
                t = int(rng.integers(14, len(m) - 14))
                for kind in ("change", "read", "any"):
                    r["null"][kind] += aligned(start + dt.timedelta(days=t), ev[kind]) / 200.0
    res = {"series_with_events": tot["series"], "series_with_onset": tot["series_with_onset"],
           "onsets": tot["n"], "resources": len(per_res)}
    keys = list(per_res)
    for kind in ("change", "read", "any"):
        o = sum(per_res[k]["obs"][kind] for k in keys); nl = sum(per_res[k]["null"][kind] for k in keys)
        n = sum(per_res[k]["n"] for k in keys)
        # resource-level bootstrap of the lift
        boots = []
        for _ in range(4000):
            pick = rng.choice(len(keys), len(keys))
            oo = sum(per_res[keys[i]]["obs"][kind] for i in pick); nn = sum(per_res[keys[i]]["null"][kind] for i in pick)
            tt = sum(per_res[keys[i]]["n"] for i in pick)
            boots.append((oo / tt, nn / tt))
        b = np.array(boots)
        res[kind] = {"observed_rate": o / n, "null_rate": nl / n,
                     "diff_ci95": [float(np.percentile(b[:, 0] - b[:, 1], 2.5)), float(np.percentile(b[:, 0] - b[:, 1], 97.5))]}
    Path("docs/patent_evaluation").mkdir(parents=True, exist_ok=True)
    json.dump(res, open("docs/patent_evaluation/corestack_alignment.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
