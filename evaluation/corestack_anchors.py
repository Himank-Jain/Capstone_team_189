"""
Anchor analysis on real CoreStack telemetry.

An "anchor" is evidence from OUTSIDE an entity's own history that a sustained level
shift is legitimate:
  C  control-plane: a change event on the same resource within +/-3 days of onset
  K  cohort: >= 30% of peer series (same category+metric, overlapping in time, other
     resources) shifted the same direction by >= 1.5 scale units within +/-7 days
For each natural onset we record which anchors fire (true-positive side). For the same
number of onsets placed at random days on the same series (the stand-in for an
unexplained shift, which is what a data-plane attack looks like) we record how often
each anchor fires by chance (false-anchor side).
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from evaluation.corestack import daily_medians, load_events, load_series
from evaluation.corestack_alignment import onsets

rng = np.random.default_rng(1)


def prep():
    S = load_series(); E = load_events()
    items = []
    for key, rec in S.items():
        m = daily_medians(rec["values"])
        start = dt.date.fromisoformat(rec["start"])
        items.append({"key": key, "rid": key[0].lower(), "sub": key[0].split("/")[2].lower() if key[0].count("/") > 2 else "", "cat": key[2], "metric": key[1],
                      "m": m, "start": start, "ev": E.get(key[0].lower())})
    return items


def shift_at(it, day: dt.date):
    """signed shift in robust units at calendar day (None if not covered)."""
    t = (day - it["start"]).days
    m = it["m"]
    if t < 14 or t + 7 > len(m):
        return None
    prior = m[t - 14:t]
    scale = max(1.4826 * np.median(np.abs(prior - np.median(prior))), 0.05 * (np.median(np.abs(m)) + 1e-9), 1e-9)
    return (np.median(m[t:t + 7]) - np.median(prior)) / scale


def cohort_fraction(items, it, day, scope):
    s0 = shift_at(it, day)
    if s0 is None or s0 == 0:
        return None
    peers = [p for p in items if p is not it and p["cat"] == it["cat"] and p["metric"] == it["metric"] and p["rid"] != it["rid"]
             and (scope == "all" or p["sub"] == it["sub"])]
    agree = tot = 0
    for p in peers:
        best = None
        for off in range(-7, 8):
            v = shift_at(p, day + dt.timedelta(days=off))
            if v is not None and (best is None or abs(v) > abs(best)):
                best = v
        if best is None:
            continue
        tot += 1
        agree += (np.sign(best) == np.sign(s0)) and abs(best) >= 1.5
    return (agree / tot, tot) if tot >= 3 else None


def anchors(items, it, day, scope):
    ev = it["ev"]
    c = bool(ev) and any(abs((e - day).days) <= 3 for e in ev["change"])
    cf = cohort_fraction(items, it, day, scope)
    k = None if cf is None else cf[0] >= 0.30
    return c, k


def main():
    items = prep()
    out = {}
    for scope in ("all", "subscription"):
        nat, rnd = [], []
        for it in items:
            if it["ev"] is None:
                continue
            ons = onsets(it["m"])
            for t in ons:
                day = it["start"] + dt.timedelta(days=t)
                nat.append((it["rid"], *anchors(items, it, day, scope)))
            for _ in ons:
                for _r in range(20):
                    t = int(rng.integers(14, len(it["m"]) - 14))
                    rnd.append((it["rid"], *anchors(items, it, it["start"] + dt.timedelta(days=t), scope)))
        def rates(rows):
            rows = [r for r in rows if r[2] is not None]
            n = len(rows)
            c = sum(r[1] for r in rows) / n; k = sum(r[2] for r in rows) / n
            either = sum(r[1] or r[2] for r in rows) / n; both = sum(r[1] and r[2] for r in rows) / n
            return {"n": n, "C": c, "K": k, "C_or_K": either, "C_and_K": both}
        out[scope] = {"natural": rates(nat), "random": rates(rnd),
                      "n_resources_natural": len({r[0] for r in nat if r[2] is not None})}
    Path("docs/patent_evaluation/corestack_anchors.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
