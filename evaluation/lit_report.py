"""
Summarise evaluation.lit_attacks:  python -m evaluation.lit_report <dataset> [fpr_target]

Included entities are clean (stable, ambient-free) and the attack must be material:
  frog g   the attack's final shift is between 1 and 100 scale units (the entity's average level times g^weeks - 1, over its scale)
  greedy   the attacker reaches its goal (6 scale units) against the unprotected adaptive baseline
Rates carry 95% intervals from a bootstrap over whole source series.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np

DATASET = sys.argv[1]
TARGET = sys.argv[2] if len(sys.argv) > 2 else "0.05"
FAMILY = "cs" if DATASET.startswith("cs") else "nab"
EV = 60 if FAMILY == "cs" else 90
OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"
D = json.load(open(OUT / f"lit_{DATASET}_{TARGET}.json"))
ROWS = [r for r in D["rows"] if r["stable"] and r["ambient_free"]]
rng = np.random.default_rng(0)


def boot(rows, f, reps=2000):
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
        bs.append(np.mean([x for i in pick for x in vals[keys[i]]]))
    return {"rate": pt, "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)), "n": len(rows), "sources": len(keys)}


def fm(x):
    return "-" if x is None else f"{100*x['rate']:.0f}% ({100*x['lo']:.0f}-{100*x['hi']:.0f})"


def included(scen):
    if scen == "greedy":
        return [r for r in ROWS if r["res"]["adaptive"]["greedy"]["goal_day"] is not None]
    return [r for r in ROWS if 1.0 <= r["frog_sigma"][scen] <= 100.0]


def main():
    labs = list(ROWS[0]["res"])
    scens = [k for k in ROWS[0]["res"]["adaptive"]]
    res = {"dataset": DATASET, "clean_entities": len(ROWS), "clean_sources": len({r["source"] for r in ROWS}), "scenarios": {}}
    print(f"== {DATASET}: clean entities {res['clean_entities']} from {res['clean_sources']} sources")
    for scen in scens:
        inc = included(scen)
        res["scenarios"][scen] = {"n": len(inc), "sources": len({r["source"] for r in inc}), "strategies": {}}
        print(f"\n-- {scen}: {len(inc)} entities from {len({r['source'] for r in inc})} sources")
        print(f"{'strategy':<14}{'detected':<16}{'days to detect':<16}{'silent σ at 1st alert (med/p90)':<34}{'stored σ at end (med/p90)':<28}" + ("reached goal" if scen == 'greedy' else ''))
        for lab in labs:
            det = boot(inc, lambda r: any(d >= EV for d in r["res"][lab][scen]["spec"]))
            ttd = [min(d for d in r["res"][lab][scen]["spec"] if d >= EV) - EV for r in inc if any(d >= EV for d in r["res"][lab][scen]["spec"])]
            sil = [r["res"][lab][scen]["first_alert_drift"] if r["res"][lab][scen]["first_alert_drift"] is not None else r["res"][lab][scen]["drift_final"] for r in inc]
            fin = [r["res"][lab][scen]["drift_final"] for r in inc]
            goal = boot(inc, lambda r: r["res"][lab][scen]["goal_day"] is not None) if scen == "greedy" else None
            q = lambda v, p: float(np.percentile(v, p)) if v else float("nan")
            row = {"detected": det, "days_to_detect_median": q(ttd, 50), "silent_median": q(sil, 50), "silent_p90": q(sil, 90), "final_median": q(fin, 50), "final_p90": q(fin, 90), "reached_goal": goal}
            res["scenarios"][scen]["strategies"][lab] = row
            print(f"{lab:<14}{fm(det):<16}{q(ttd,50):<16.0f}{q(sil,50):>6.2f} / {q(sil,90):<6.2f}{'':<20}{q(fin,50):>6.2f} / {q(fin,90):<6.2f}{'':<12}" + (fm(goal) if goal else ''))
    (OUT / f"lit_results_{DATASET}_{TARGET}.json").write_text(json.dumps(res, indent=1))


main()
