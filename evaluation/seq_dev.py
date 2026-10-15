"""
Development-set comparison of sequential triggers (offline, on daily residual series).

    python -m evaluation.seq_dev <dataset> [<dataset> ...]         e.g.  cs_dev cs_fresh2

For every entity and every trigger, the per-entity label-free threshold at nominal level q is the q-quantile of the trigger's
largest value over B clean futures drawn from the entity's own calibration days.  Sweeping q gives one operating curve per
trigger: the real false-alarm rate (stable, ambient-free entities, real future, no injection) against the detection rate on
injected drifts.  Nothing here looks at a held-out set.
"""
from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np

from evaluation import seq_offline as so

QS = [0.5, 0.75, 0.9, 0.95, 0.975, 0.99, 0.995, 0.999, 0.9995, 1.0]
NCAL = 30  # calibration days (SNAPSHOT_DAY..BOUNDS_DAY-1)
B = 300


def groups(names):
    g = defaultdict(list)
    for n in names:
        if n.startswith("R1_"):
            g["R1_total_" + n.rsplit("_", 1)[1]].append(n)
        elif n.startswith("R2_"):
            g["R2_rate_" + n.rsplit("_", 1)[1]].append(n)
        elif n.startswith("S30_"):
            g["S30_" + n.rsplit("_", 1)[1]].append(n)
        elif n == "fast4":
            g["fast4"].append(n)
        elif n.startswith("benign_"):
            g["benign_" + n.split("_")[1]].append(n)
    return g


SOURCES = ("", "#med", "#trim")  # daily mean / median / middle-half mean of the hourly residuals
FLOORS = (0.05, 0.2)
DETS = ("cusum0.5", "cusum1.0", "win14")


def per_entity(datasets, block=1):
    rows = []
    for ds in datasets:
        d, X = so.load(ds)
        snap = d["snapshot_day"]
        for m in d["meta"]:
            i = m["idx"]
            x = X[i]
            rec = {"ds": ds, "idx": i, "stable": m["stable"], "amb": m["ambient_free"], "group": m["group"], "source": m["source"],
                   "null": {}, "M": {}}
            for src in SOURCES:
                ctrl = x["control" + src]
                T = len(ctrl) - NCAL
                dt_all = so.daytype(len(ctrl), snap, m.get("wk0", 0))
                rng = np.random.default_rng(1000 * (hash(ds) % 997) + i)
                fut = so.null_futures(ctrl[:NCAL], dt_all, NCAL, T, B, rng, block)
                for fl in FLOORS:
                    mu, sd = so.reference(ctrl, NCAL, fl)
                    zf = so.standardise(fut, mu, sd)
                    for dn in DETS:
                        key = f"{dn}|{src or 'mean'}|{fl}"
                        rec["null"][key] = np.sort(so.DETECTORS[dn](zf).max(axis=-1))
                        rec["M"][key] = {}
                        for sc in x:
                            if not sc.endswith(src) or (src == "" and "#" in sc):
                                continue
                            base = sc[: len(sc) - len(src)] if src else sc
                            z = so.standardise(x[sc][NCAL:], mu, sd)
                            rec["M"][key][base] = float(so.DETECTORS[dn](z).max())
            rows.append(rec)
    return rows


def operating_points(rows, dn, scen_groups, mode, targets=(0.02, 0.05, 0.10), q=0.975):
    """Sweep one threshold parameter and report, for each FPR target, the smallest parameter that meets it.
    mode "global": h = c on the raw statistic;  mode "rel": h = m * (q-quantile of the entity's own null)."""
    ok = [r for r in rows if r["stable"] and r["amb"]]
    if mode == "global":
        grid = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 18.0, 24.0, 30.0, 40.0, 50.0, 80.0, 120.0]
        thr = lambda r, c: c
    else:
        grid = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 12.0]
        thr = lambda r, m: m * max(np.quantile(r["null"][dn], q, method="higher"), 1e-9)
    res = []
    for c in grid:
        fpr = np.mean([r["M"][dn]["control"] > thr(r, c) for r in ok])
        tpr = {g: np.mean([np.mean([r["M"][dn][n] > thr(r, c) for n in names]) for r in ok]) for g, names in scen_groups.items()}
        res.append((c, fpr, tpr))
    out = {}
    for t in targets:
        meet = [x for x in res if x[1] <= t]
        out[t] = min(meet, key=lambda x: x[0]) if meet else None
    return out, len(ok), res


def main():
    datasets = sys.argv[1:]
    rows = per_entity(datasets, 1)
    detectors = list(rows[0]["M"])
    d0, X0 = so.load(datasets[0])
    sg = groups([k for k in X0[0].keys() if "#" not in k])
    show = ["S30_1.0", "S30_2.0", "S30_3.0", "fast4", "R1_total_0.3", "R1_total_0.6", "R1_total_0.9", "R2_rate_0.01", "benign_1.0"]
    print(f"datasets={datasets} entities={len(rows)}  (TPR and FPR on stable, ambient-free entities only)")
    for mode in ("global", "rel"):
        print(f"\n##### threshold mode: {mode}")
        for dn in detectors:
            op, nok, _ = operating_points(rows, dn, sg, mode)
            print(f"-- {dn}  n={nok}")
            print("   target  param   FPR   " + "  ".join(f"{s[:12]:>12}" for s in show))
            for t, x in op.items():
                if x is None:
                    print(f"   {t:<6} unreachable")
                    continue
                c, fpr, tpr = x
                print(f"   {t:<6} {c:<6g} {100*fpr:5.1f}  " + "  ".join(f"{100*tpr[s]:12.1f}" for s in show))


if __name__ == "__main__":
    main()
