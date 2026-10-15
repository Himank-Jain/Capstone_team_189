import json, numpy as np
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
R = json.load(open(ROOT / "docs/patent_evaluation/absorption_raw.json"))
S0 = 30

def tta(drift, first_inc, X):
    """days from the first incident until stored displacement >= X (None = never within the run)."""
    if first_inc is None: return None
    for i, d in enumerate(drift):
        day = S0 + i
        if day >= first_inc and d >= X:
            return day - first_inc
    return None

def summarize(rows):
    out = {}
    for v in rows[0]["res"]:
        o = {}
        for scen in ("attack", "cattack"):
            for X in (2.0, 4.0):
                sel = [r for r in rows if r["target"] >= X + 0.01 and r["res"][v][scen]["first_inc"] is not None]
                ts = [tta(r["res"][v][scen]["drift"], r["res"][v][scen]["first_inc"], X) for r in sel]
                reach = [t for t in ts if t is not None]
                o[f"{scen}_to_{X:g}sigma"] = {"n": len(sel), "reached": len(reach),
                                             "median_days": float(np.median(reach)) if reach else None,
                                             "p10_days": float(np.percentile(reach, 10)) if reach else None}
        # largest 14-day gain in stored displacement (per-window cap check), after the first incident
        gains = []
        for r in rows:
            a = r["res"][v]["attack"]
            if a["first_inc"] is None: continue
            d = a["drift"]; fi = a["first_inc"] - S0
            gains.append(max((d[i] - d[i - 14] for i in range(max(fi, 14), len(d))), default=0.0))
        o["max_14d_gain_median"] = float(np.median(gains)); o["max_14d_gain_p90"] = float(np.percentile(gains, 90))
        out[v] = o
    return out

held = [r for r in R if r["heldout"]]
res = {"heldout": summarize(held), "all": summarize(R), "n_heldout": len(held), "n_all": len(R)}
(ROOT / "docs/patent_evaluation/absorption_results.json").write_text(json.dumps(res, indent=1))
for lab in ("heldout", "all"):
    print("=====", lab)
    for v, o in res[lab].items():
        print(v)
        for k, x in o.items(): print("   ", k, x)
