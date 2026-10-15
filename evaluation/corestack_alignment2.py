"""
Re-test of the control-plane pivot with a stricter event definition and per-metric-family breakdown.

Admin change = category 'Administrative' operation that writes/deletes/starts/stops/scales/patches (listKeys etc.
and policy/recommendation/health bookkeeping excluded). Usage-type metrics (Egress, Ingress, Transactions) are
expected to co-move with data-plane activity (key listing, access), so a control-plane signal should lift
configuration-type metrics (UsedCapacity, Availability, latency, disk) and NOT be the explanation for usage.
Null = same number of onsets at random days on the same series (per-resource, so event density is preserved).
"""
from __future__ import annotations
import datetime as dt, json, pickle
from collections import defaultdict
from pathlib import Path
import numpy as np
from evaluation.corestack import CHANGE_RE, NOISE_RE, DATA, daily_medians, load_series
from evaluation.corestack_alignment import onsets, WIN

rng = np.random.default_rng(5)
USAGE = {"Egress", "Ingress", "Transactions", "BytesReceived", "BytesSent", "Requests"}


def admin_events():
    out = defaultdict(set)
    for rid, day, op, cat, st, n in pickle.load(open(DATA / "corestack_events_daily.pkl", "rb")):
        if cat == "Administrative" and CHANGE_RE.search(op) and not NOISE_RE.search(op) and st in ("Succeeded", "Started", "Accepted"):
            out[rid].add(dt.date.fromisoformat(day))
    return out


def al(day, evs): return any(abs((e - day).days) <= WIN for e in evs)


def main():
    S, E = load_series(), admin_events()
    fam = defaultdict(lambda: defaultdict(lambda: {"n": 0, "obs": 0, "null": 0.0}))
    for key, rec in S.items():
        rid = key[0].lower(); evs = E.get(rid, set())
        m = daily_medians(rec["values"]); start = dt.date.fromisoformat(rec["start"])
        ons = onsets(m)
        group = "usage" if key[1] in USAGE else "config"
        for g in (group, "all"):
            f = fam[g][rid]
            for t in ons:
                f["n"] += 1; f["obs"] += al(start + dt.timedelta(days=t), evs)
            for _ in range(len(ons)):
                for _r in range(200):
                    t = int(rng.integers(14, len(m) - 14))
                    f["null"] += al(start + dt.timedelta(days=t), evs) / 200.0
    res = {}
    for g, per in fam.items():
        keys = [k for k, v in per.items() if v["n"] > 0]
        n = sum(per[k]["n"] for k in keys)
        if n == 0: continue
        o = sum(per[k]["obs"] for k in keys); nl = sum(per[k]["null"] for k in keys)
        boots = []
        for _ in range(3000):
            pick = rng.choice(len(keys), len(keys))
            tt = sum(per[keys[i]]["n"] for i in pick)
            if tt: boots.append((sum(per[keys[i]]["obs"] for i in pick) - sum(per[keys[i]]["null"] for i in pick)) / tt)
        res[g] = {"onsets": n, "resources": len(keys), "observed": o / n, "null": nl / n,
                  "diff_ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]}
    Path("docs/patent_evaluation/corestack_alignment_admin.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))

if __name__ == "__main__":
    main()
