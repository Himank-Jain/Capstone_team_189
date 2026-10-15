"""Summarise schema_free_real_<dataset>.json: mean AUC per condition with bootstrap over resources."""
from __future__ import annotations
import json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"
RNG = np.random.default_rng(20261015)


def _ci(by, key, n=2000):
    keys = sorted(by)
    vals = []
    for _ in range(n):
        pick = RNG.integers(0, len(keys), len(keys))
        xs = [x for i in pick for x in by[keys[i]] if x is not None]
        vals.append(np.mean(xs) if xs else np.nan)
    return float(np.nanpercentile(vals, 2.5)), float(np.nanpercentile(vals, 97.5))


def main(ds, tag=""):
    rows = json.loads((OUT / f"schema_free_real_{ds}{tag}.json").read_text())["rows"]
    res = {}
    for label, sel, keys in [
        ("in-vocabulary entities", lambda r: r["in_vocab"], ["in_vocab_auc", "renamed_pass", "renamed_online", "zscore"]),
        ("genuinely unseen schema", lambda r: not r["in_vocab"], ["natural_pass", "natural_online", "zscore"]),
    ]:
        sub = [r for r in rows if sel(r)]
        if not sub:
            continue
        print(f"== {ds}: {label}: {len(sub)} entities from {len({r['resource'] for r in sub})} resources")
        out = {}
        for k in keys:
            by = defaultdict(list)
            for r in sub:
                if r.get(k) is not None:
                    by[r["resource"]].append(r[k])
            xs = [x for v in by.values() for x in v]
            if not xs:
                continue
            lo, hi = _ci(by, k)
            out[k] = {"n": len(xs), "mean_auc": float(np.mean(xs)), "ci": [lo, hi], "median": float(np.median(xs)),
                      "share_ge_0.9": float(np.mean(np.array(xs) >= 0.9))}
            print(f"   {k:16s} n={len(xs):3d} mean AUC {np.mean(xs):.3f} [{lo:.3f},{hi:.3f}] median {np.median(xs):.3f} share>=0.9 {np.mean(np.array(xs)>=0.9):.2f}")
        res[label] = out
    (OUT / f"schema_free_real_summary_{ds}{tag}.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
