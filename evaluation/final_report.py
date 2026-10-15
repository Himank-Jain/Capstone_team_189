"""
Summarise a final_eval run:  python -m evaluation.final_report <dataset> [fpr_target]

n is reported in independent series (sources) as well as entities; every rate carries a 95% interval from a bootstrap that
resamples whole sources (clusters), so dependent replicas of one series cannot inflate certainty.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np

DATASET = sys.argv[1]
TARGET = sys.argv[2] if len(sys.argv) > 2 else "0.05"
FAMILY = "cs" if DATASET.startswith("cs") else "nab"
END = {"cs_dev": 100, "cs_fresh": 90}.get(DATASET, 220)
EV = 60 if FAMILY == "cs" else 90
LONG_RAMP = 20 if FAMILY == "cs" else 60
OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"
D = json.load(open(OUT / f"final_{DATASET}_{TARGET}.json"))
ROWS = D["rows"]
LABELS = list(ROWS[0]["res"])
rng = np.random.default_rng(0)


def anyin(a, lo, hi=None):
    return any(x >= lo and (hi is None or x < hi) for x in a)


def boot_rate(rows, f, reps=2000):
    """rate of f(row) over rows, with a source-clustered bootstrap interval."""
    if not rows:
        return None
    vals = {}
    for r in rows:
        vals.setdefault(r["source"], []).append(f(r))
    keys = list(vals)
    pt = float(np.mean([x for v in vals.values() for x in v]))
    bs = []
    for _ in range(reps):
        pick = rng.choice(len(keys), len(keys))
        xs = [x for i in pick for x in vals[keys[i]]]
        bs.append(np.mean(xs))
    return {"rate": pt, "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)),
            "n": len(rows), "k": int(sum(x for v in vals.values() for x in v)), "sources": len(keys)}


def fmt(x):
    return "   -   " if x is None else f"{x['rate']:.2f} [{x['lo']:.2f},{x['hi']:.2f}]"


def disp(rows, lab, scen):
    out = []
    for r in rows:
        c = r["res"][lab][scen]
        d = c["first_alert_drift"]
        out.append(d if d is not None else c["drift_final"])  # undetected: whatever the baseline had absorbed by the end
    return out


def summarise():
    clean = [r for r in ROWS if r["stable"] and r["ambient_free"]]
    shifted = [r for r in ROWS if not r["stable"]]
    res = {"dataset": DATASET, "target_fpr": TARGET, "thresholds": D["thresholds"],
           "n_entities": len(ROWS), "n_sources": len({r["source"] for r in ROWS}),
           "n_clean_entities": len(clean), "n_clean_sources": len({r["source"] for r in clean}),
           "n_shifted_entities": len(shifted), "n_shifted_sources": len({r["source"] for r in shifted}), "strategies": {}}
    for lab in LABELS:
        s = {}
        s["fpr"] = boot_rate(clean, lambda r: anyin(r["res"][lab]["control"]["spec"], EV))
        for scen, win in (("stealth1.0", LONG_RAMP + 30), ("stealth2.0", LONG_RAMP + 30), ("stealth3.0", LONG_RAMP + 30),
                          ("fast4", 40), ("local4", LONG_RAMP + 30), ("poisoned", None)):
            s["tpr_" + scen] = boot_rate(clean, lambda r, scen=scen, win=win: anyin(r["res"][lab][scen]["spec"], EV, EV + win if win else None))
        for scen in ("stealth2.0", "stealth3.0", "fast4"):
            v = disp(clean, lab, scen)
            s["disp_" + scen] = {"median": float(np.median(v)), "p90": float(np.percentile(v, 90)), "max": float(np.max(v))}
        # attack absorbed at end: stored baseline carries >= half of the injected shift (3 sigma stealth)
        s["absorbed_stealth3"] = boot_rate(clean, lambda r: r["res"][lab]["stealth3.0"]["drift_final"] >= 1.5)
        # injected legitimate growth (sustained, no change event unless drawn)
        b = [r for r in clean if r["benign_mag"] >= 1.0]
        s["benign_flagged"] = boot_rate(b, lambda r: anyin(r["res"][lab]["benign"]["spec"], EV))
        bf = [r for r in b if anyin(r["res"][lab]["benign"]["spec"], EV)]
        s["benign_unresolved_of_flagged"] = boot_rate(bf, lambda r: r["res"][lab]["benign"]["tail_alert"] or r["res"][lab]["benign"]["tail_held"])
        # genuinely shifted real series (CoreStack): control run only
        if shifted:
            s["real_shift_flagged"] = boot_rate(shifted, lambda r: anyin(r["res"][lab]["control"]["spec"], EV))
            sf = [r for r in shifted if anyin(r["res"][lab]["control"]["spec"], EV)]
            s["real_shift_unresolved_of_flagged"] = boot_rate(sf, lambda r: r["res"][lab]["control"]["tail_alert"] or r["res"][lab]["control"]["tail_held"])
        g = [r["res"][lab]["stealth3.0"]["post_gain14"] for r in clean if r["res"][lab]["stealth3.0"].get("post_gain14") is not None]
        s["post_gain14_stealth3"] = ({"n": len(g), "median": float(np.median(g)), "p90": float(np.percentile(g, 90)), "max": float(np.max(g))} if g else None)
        res["strategies"][lab] = s
    return res


if __name__ == "__main__":
    R = summarise()
    (OUT / f"final_results_{DATASET}_{TARGET}.json").write_text(json.dumps(R, indent=1))
    print(f"== {DATASET} target FPR {TARGET}  entities {R['n_entities']} sources {R['n_sources']} | clean {R['n_clean_entities']} ({R['n_clean_sources']} sources) | shifted {R['n_shifted_entities']} ({R['n_shifted_sources']} sources)")
    print("thresholds", R["thresholds"])
    hdr = f"{'strategy':<15}{'FPR':<19}{'1σ':<19}{'2σ':<19}{'3σ':<19}{'fast4σ':<19}{'local4σ':<19}{'poisoned':<19}"
    print(hdr)
    for lab, s in R["strategies"].items():
        print(f"{lab:<15}{fmt(s['fpr']):<19}{fmt(s['tpr_stealth1.0']):<19}{fmt(s['tpr_stealth2.0']):<19}{fmt(s['tpr_stealth3.0']):<19}{fmt(s['tpr_fast4']):<19}{fmt(s['tpr_local4']):<19}{fmt(s['tpr_poisoned']):<19}")
    print("\nsilent displacement at first alert (median / p90 / max, σ) and end-state absorption")
    for lab, s in R["strategies"].items():
        d2, d3, df = s["disp_stealth2.0"], s["disp_stealth3.0"], s["disp_fast4"]
        print(f"{lab:<15}2σ {d2['median']:.2f}/{d2['p90']:.2f}/{d2['max']:.2f}  3σ {d3['median']:.2f}/{d3['p90']:.2f}/{d3['max']:.2f}  fast {df['median']:.2f}/{df['p90']:.2f}/{df['max']:.2f}  absorbed@end {fmt(s['absorbed_stealth3'])}")
    print("\nlegitimate growth (injected >=1σ) and real shifts: flagged / unresolved-of-flagged")
    for lab, s in R["strategies"].items():
        line = f"{lab:<15}benign flagged {fmt(s['benign_flagged'])} unresolved {fmt(s['benign_unresolved_of_flagged'])}"
        if "real_shift_flagged" in s:
            line += f" | real shifts flagged {fmt(s['real_shift_flagged'])} unresolved {fmt(s['real_shift_unresolved_of_flagged'])}"
        print(line)
    print("\nlargest rise of stored displacement in any 14-day window after the first alert (3σ stealth; σ units)")
    for lab, s in R["strategies"].items():
        g = s["post_gain14_stealth3"]
        print(f"{lab:<15}" + ("-" if g is None else f"n {g['n']}  median {g['median']:.2f}  p90 {g['p90']:.2f}  max {g['max']:.2f}"))
