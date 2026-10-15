"""Aggregate attribution_<dataset>.json: top-1, top-2, flagged and distractor counts, snapshot vs adaptive, bootstrap over resources."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"
RNG = np.random.default_rng(20261015)


def _boot(by_res: dict, stat, n=2000):
    keys = sorted(by_res)
    vals = []
    for _ in range(n):
        pick = RNG.integers(0, len(keys), len(keys))
        vals.append(stat([r for i in pick for r in by_res[keys[i]]]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def _is_network(resource: str) -> bool:
    return "/providers/microsoft.network/" in resource.lower()


def main(ds: str, variant: str = "pk24", nonet: bool = False):
    d = json.loads((OUT / f"attribution_{ds}.json").read_text())
    rows = [r for r in d["rows"] if r.get("variant", "pk3") == variant and not (nonet and _is_network(r["resource"]))]
    probes = d["probes"]
    idx = defaultdict(dict)
    for r in rows:
        idx[(r["resource"], r["target"], r["scenario"], r["probe"])][r["baseline"]] = r
    tag = ", without Microsoft.Network resources" if nonet else ""
    print(f"== {ds} [{variant}{tag}]: probes {probes}; resources {len({r['resource'] for r in rows})}; metrics per resource "
          f"{sorted({r['n_metrics'] for r in rows})}")
    out = {}
    for sc in ("stealth2", "stealth3", "fast4", "control"):
        for p in probes:
            by = defaultdict(list)
            for (rid, tgt, s, pp), v in idx.items():
                if s == sc and pp == p and "snapshot" in v and "adaptive" in v:
                    by[rid].append(v)
            if not by:
                continue
            n = sum(len(x) for x in by.values())
            line = {"n": n}
            for b in ("snapshot", "adaptive"):
                top1 = lambda rs, b=b: float(np.mean([x[b]["rank"] == 1 for x in rs]))
                top2 = lambda rs, b=b: float(np.mean([x[b]["rank"] is not None and x[b]["rank"] <= 2 for x in rs]))
                flg = lambda rs, b=b: float(np.mean([(x[b]["target_contrib"] or 0) >= 3.0 for x in rs]))
                dis = lambda rs, b=b: float(np.mean([x[b]["n_flag_nontarget"] for x in rs]))
                anyd = lambda rs, b=b: float(np.mean([x[b]["n_flag_nontarget"] >= 1 for x in rs]))
                allrs = [x for v in by.values() for x in v]
                line[b] = {"top1": top1(allrs), "top1_ci": _boot(by, top1), "top2": top2(allrs), "flagged": flg(allrs),
                           "mean_distractors": dis(allrs), "any_distractor": anyd(allrs)}
            diff = lambda rs: float(np.mean([(x["snapshot"]["rank"] == 1) - (x["adaptive"]["rank"] == 1) for x in rs]))
            allrs = [x for v in by.values() for x in v]
            line["top1_diff_snapshot_minus_adaptive"] = diff(allrs)
            line["diff_ci"] = _boot(by, diff)
            out[f"{sc}@{p}"] = line
            if sc != "control":
                print(f"{sc:9s} day {p:3d} n={n:3d} | snapshot top1 {line['snapshot']['top1']:.2f} "
                      f"[{line['snapshot']['top1_ci'][0]:.2f},{line['snapshot']['top1_ci'][1]:.2f}] top2 {line['snapshot']['top2']:.2f} "
                      f"dist {line['snapshot']['mean_distractors']:.2f} | adaptive top1 {line['adaptive']['top1']:.2f} "
                      f"[{line['adaptive']['top1_ci'][0]:.2f},{line['adaptive']['top1_ci'][1]:.2f}] top2 {line['adaptive']['top2']:.2f} "
                      f"dist {line['adaptive']['mean_distractors']:.2f} | diff {line['top1_diff_snapshot_minus_adaptive']:+.2f} "
                      f"[{line['diff_ci'][0]:+.2f},{line['diff_ci'][1]:+.2f}]")
            else:
                print(f"control   day {p:3d} n={n:3d} | distractors per case snapshot {line['snapshot']['mean_distractors']:.2f} "
                      f"(any {line['snapshot']['any_distractor']:.2f}) adaptive {line['adaptive']['mean_distractors']:.2f} "
                      f"(any {line['adaptive']['any_distractor']:.2f})")
    # top-3 only where >= 5 metrics
    for sc in ("stealth2", "stealth3", "fast4"):
        for p in probes:
            sel = [(v["snapshot"], v["adaptive"]) for (rid, tgt, s, pp), v in idx.items()
                   if s == sc and pp == p and "snapshot" in v and "adaptive" in v and v["snapshot"]["n_metrics"] >= 5]
            if sel:
                t3 = lambda k: float(np.mean([x[k]["rank"] is not None and x[k]["rank"] <= 3 for x in
                                              [dict(snapshot=a, adaptive=b) for a, b in sel]]))
                print(f"top-3 where metrics>=5 {sc}@{p}: n={len(sel)} snapshot {t3('snapshot'):.2f} adaptive {t3('adaptive'):.2f}")
    (OUT / f"attribution_summary_{ds}_{variant}{'_nonet' if nonet else ''}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "pk24", len(sys.argv) > 3 and sys.argv[3] == "nonet")
