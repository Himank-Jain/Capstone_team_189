"""
Summarise evaluation.ablation_eval:  python -m evaluation.ablation_report <dataset> <ablation|curve|curve_ev0>

Columns and tests were written down before the dev results were read (docs/patent_evaluation/ABLATION.md, "Plan").

Entity sets   clean = stable and ambient-free (the same definition as final_report.py); growth = clean entities whose injected
              legitimate growth is at least 1 scale unit.
Per-entity outcomes (0/1)
  fa          a false alert on the control run (an incident / alert on or after the event day)
  det3        the 3 sigma stealth attack is alerted within the report window
  abs3        the stored baseline carries >= 1.5 sigma of the 3 sigma stealth attack at the end of the run
  gflag       the injected legitimate growth is alerted
  gunres      ... and is still alerting or held at the end
  pdet        the poisoned calibration is alerted
  goal        the greedy attacker reaches its goal (6 sigma stored displacement); only entities where it does against the
              adaptive baseline are used
Joint columns (per entity)
  C1  quiet and safe      not fa  and  det3  and  not abs3
  C2  ... and operable    C1  and  not gunres          (growth entities only)
  C3  governed under attack   not fa  and  pdet  and  not goal      (greedy-applicable entities only)
Interaction test (super-additivity) for a joint column Y on the four corners no-parts / claim 1 alone / claim 2 alone / both:
  I = Y(full) - Y(H) - Y(S) + Y(adaptive)   (paired per entity, bootstrap over whole resources)
  I > 0 with an interval above 0: the design does better than the two parts' separate gains added up.
  Also reported: Y(full) - max(Y(H), Y(S)): whether the design beats the better of its parts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

DATASET, SET = sys.argv[1], sys.argv[2]
FAMILY = "cs" if DATASET.startswith("cs") else "nab"
EV = 60
LONG_RAMP = 20
WIN = LONG_RAMP + 30
OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"
D = json.load(open(OUT / f"ablation_{SET}_{DATASET}.json"))
ROWS = D["rows"]
LABELS = list(ROWS[0]["res"])
rng = np.random.default_rng(0)


def anyin(a, lo, hi=None):
    return any(x >= lo and (hi is None or x < hi) for x in a)


def fa(r, lab): return anyin(r["res"][lab]["control"]["spec"], EV)
def det3(r, lab): return anyin(r["res"][lab]["stealth3.0"]["spec"], EV, EV + WIN)
def abs3(r, lab): return r["res"][lab]["stealth3.0"]["drift_final"] >= 1.5
def gflag(r, lab): return anyin(r["res"][lab]["benign"]["spec"], EV)
def gunres(r, lab): return gflag(r, lab) and (r["res"][lab]["benign"]["tail_alert"] or r["res"][lab]["benign"]["tail_held"])
def pdet(r, lab): return anyin(r["res"][lab]["poisoned"]["spec"], EV)
def goal(r, lab): return r["res"][lab]["greedy"]["goal_day"] is not None
def c1(r, lab): return (not fa(r, lab)) and det3(r, lab) and (not abs3(r, lab))
def c2(r, lab): return c1(r, lab) and not gunres(r, lab)
def c3(r, lab): return (not fa(r, lab)) and pdet(r, lab) and (not goal(r, lab))


CLEAN = [r for r in ROWS if r["stable"] and r["ambient_free"]]
GROWTH = [r for r in CLEAN if r["benign_mag"] is not None and r["benign_mag"] >= 1.0]
GREEDY = [r for r in CLEAN if "greedy" in r["res"]["adaptive" if "adaptive" in r["res"] else LABELS[0]] and
          r["res"]["adaptive" if "adaptive" in r["res"] else LABELS[0]]["greedy"]["goal_day"] is not None] if SET == "ablation" else \
         [r for r in CLEAN if r["res"][LABELS[0]]["greedy"]["goal_day"] is not None or True]
SHIFTED = [r for r in ROWS if not r["stable"]]


def boot(rows, f, reps=3000):
    """mean of f over rows with a bootstrap over whole source resources; f may return a number or bool."""
    if not rows:
        return None
    by = {}
    for r in rows:
        by.setdefault(r["source"], []).append(float(f(r)))
    keys = list(by)
    pt = float(np.mean([x for v in by.values() for x in v]))
    bs = []
    for _ in range(reps):
        pick = rng.choice(len(keys), len(keys))
        bs.append(np.mean([x for i in pick for x in by[keys[i]]]))
    return {"rate": pt, "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)), "n": len(rows), "sources": len(keys)}


def pct(x):
    return "-" if x is None else f"{100 * x['rate']:.0f}% ({100 * x['lo']:.0f}-{100 * x['hi']:.0f})"


def ablation():
    res = {"dataset": DATASET, "n_entities": len(ROWS), "n_sources": len({r["source"] for r in ROWS}), "n_clean": len(CLEAN),
           "n_clean_sources": len({r["source"] for r in CLEAN}), "n_growth": len(GROWTH), "n_greedy": len(GREEDY),
           "n_greedy_sources": len({r["source"] for r in GREEDY}), "variants": {}, "interaction": {}}
    for lab in LABELS:
        s = {"fa": boot(CLEAN, lambda r: fa(r, lab)), "det3": boot(CLEAN, lambda r: det3(r, lab)), "abs3": boot(CLEAN, lambda r: abs3(r, lab)),
             "gflag": boot(GROWTH, lambda r: gflag(r, lab)),
             "gunres_of_flagged": boot([r for r in GROWTH if gflag(r, lab)], lambda r: gunres(r, lab)),
             "pdet": boot(CLEAN, lambda r: pdet(r, lab)), "goal": boot(GREEDY, lambda r: goal(r, lab)),
             "C1": boot(CLEAN, lambda r: c1(r, lab)), "C2": boot(GROWTH, lambda r: c2(r, lab)), "C3": boot(GREEDY, lambda r: c3(r, lab)),
             "fa_shifted_unres": boot([r for r in SHIFTED if anyin(r["res"][lab]["control"]["spec"], EV)],
                                      lambda r: r["res"][lab]["control"]["tail_alert"] or r["res"][lab]["control"]["tail_held"]),
             "unit_sources": sorted({u for r in ROWS for sc in r["res"][lab].values() for u in sc.get("unit_sources", [])})}
        res["variants"][lab] = s
    # interaction on the joint columns
    for col, rows, f in (("C1", CLEAN, c1), ("C2", GROWTH, c2), ("C3", GREEDY, c3)):
        if not rows:
            continue
        g = lambda lab: (lambda r: f(r, lab))
        I = boot(rows, lambda r: f(r, "full") - f(r, "H") - f(r, "S") + f(r, "adaptive"))
        gap = boot(rows, lambda r: f(r, "full") - max(f(r, "H"), f(r, "S")))
        ind = {lab: boot(rows, g(lab)) for lab in ("adaptive", "H", "S", "full")}
        res["interaction"][col] = {"n": len(rows), "values": ind, "interaction": I, "full_minus_best_part": gap}
    # what each link adds, same columns
    res["links"] = {}
    for col, rows, f in (("C1", CLEAN, c1), ("C2", GROWTH, c2), ("C3", GREEDY, c3)):
        res["links"][col] = {}
        for lab in ("HS_unlinked", "HS_unvalidated", "HS_nocap", "full_B"):
            if lab in LABELS:
                res["links"][col][lab] = boot(rows, lambda r: f(r, "full") - f(r, lab))
    return res


def curve():
    cols = {}
    for lab in LABELS:
        units = [r["res"][lab]["stealth3.0"]["unit"] for r in CLEAN if r["res"][lab]["stealth3.0"].get("unit")]
        cols[lab] = {
            "median_bound_unit": float(np.median(units)) if units else None,
            "absorbed3": boot(CLEAN, lambda r: abs3(r, lab)),
            "absorbed_fast4": boot(CLEAN, lambda r: r["res"][lab]["fast4"]["drift_final"] >= 1.5),
            "stored3_median": float(np.median([r["res"][lab]["stealth3.0"]["drift_final"] for r in CLEAN])),
            "stored3_p90": float(np.percentile([r["res"][lab]["stealth3.0"]["drift_final"] for r in CLEAN], 90)),
            "det3": boot(CLEAN, lambda r: det3(r, lab)),
            "fa": boot(CLEAN, lambda r: fa(r, lab)),
            "growth_flagged": boot(GROWTH, lambda r: gflag(r, lab)),
            "growth_resolved_of_flagged": boot([r for r in GROWTH if gflag(r, lab)], lambda r: not gunres(r, lab)),
            "growth_resolved_all": boot(GROWTH, lambda r: not gunres(r, lab)),
            "real_shift_resolved_of_flagged": boot([r for r in SHIFTED if anyin(r["res"][lab]["control"]["spec"], EV)],
                                                   lambda r: not (r["res"][lab]["control"]["tail_alert"] or r["res"][lab]["control"]["tail_held"])),
            "greedy_goal": boot([r for r in CLEAN if r["res"][lab]["greedy"]["goal_day"] is not None or True], lambda r: r["res"][lab]["greedy"]["goal_day"] is not None),
            "frog_stored_p90": float(np.percentile([r["res"][lab]["frog1.15"]["drift_final"] for r in CLEAN], 90)),
            "C1": boot(CLEAN, lambda r: c1(r, lab)), "C2": boot(GROWTH, lambda r: c2(r, lab)),
        }
    # Link contrast matched on step size (fixed before the sweep was read): allowance of one validated bound (L1) against a fixed
    # allowance equal to the floor that is the bound for most entities (F0.5), same columns.
    link = {}
    if "L1" in LABELS and "F0.5" in LABELS:
        for col, rows, f in (("C1", CLEAN, c1), ("C2", GROWTH, c2)):
            link[col] = {"L1_minus_F0.5": boot(rows, lambda r: f(r, "L1") - f(r, "F0.5"))}
        link["absorbed3"] = {"L1_minus_F0.5": boot(CLEAN, lambda r: abs3(r, "L1") - abs3(r, "F0.5"))}
        link["growth_unresolved"] = {"L1_minus_F0.5": boot(GROWTH, lambda r: gunres(r, "L1") - gunres(r, "F0.5"))}
    return {"dataset": DATASET, "set": SET, "n_clean": len(CLEAN), "n_clean_sources": len({r["source"] for r in CLEAN}), "n_growth": len(GROWTH),
            "n_shifted": len(SHIFTED), "points": cols, "link_matched": link}


if __name__ == "__main__":
    if SET == "ablation":
        R = ablation()
        (OUT / f"ablation_results_{DATASET}.json").write_text(json.dumps(R, indent=1))
        print(f"== {DATASET} ablation: entities {R['n_entities']} ({R['n_sources']} resources), clean {R['n_clean']} ({R['n_clean_sources']}), growth {R['n_growth']}, greedy-applicable {R['n_greedy']} ({R['n_greedy_sources']})")
        print(f"{'variant':<16}{'false alert':<14}{'3σ det':<14}{'3σ absorbed':<14}{'growth unres':<14}{'poisoned det':<14}{'greedy goal':<14}{'C1':<14}{'C2':<14}{'C3':<14}")
        for lab, s in R["variants"].items():
            print(f"{lab:<16}{pct(s['fa']):<14}{pct(s['det3']):<14}{pct(s['abs3']):<14}{pct(s['gunres_of_flagged']):<14}{pct(s['pdet']):<14}{pct(s['goal']):<14}{pct(s['C1']):<14}{pct(s['C2']):<14}{pct(s['C3']):<14}")
        print("\ninteraction: full - H - S + adaptive   |   full - max(H, S)")
        for col, t in R["interaction"].items():
            v = t["values"]
            print(f"{col} (n={t['n']}): adaptive {pct(v['adaptive'])}  H {pct(v['H'])}  S {pct(v['S'])}  full {pct(v['full'])} | I = {100*t['interaction']['rate']:+.0f} pts [{100*t['interaction']['lo']:+.0f}, {100*t['interaction']['hi']:+.0f}] | full-best part = {100*t['full_minus_best_part']['rate']:+.0f} pts [{100*t['full_minus_best_part']['lo']:+.0f}, {100*t['full_minus_best_part']['hi']:+.0f}]")
        print("\nwhat each link adds (full minus variant, points of each joint column)")
        for col, t in R["links"].items():
            print(col, {k: f"{100*v['rate']:+.0f} [{100*v['lo']:+.0f},{100*v['hi']:+.0f}]" for k, v in t.items()})
    else:
        R = curve()
        (OUT / f"allowance_curve_{SET}_{DATASET}.json").write_text(json.dumps(R, indent=1))
        print(f"== {DATASET} {SET}: clean {R['n_clean']} ({R['n_clean_sources']} resources), growth {R['n_growth']}, shifted {R['n_shifted']}")
        print(f"{'point':<10}{'unit σ':<8}{'3σ absorbed':<15}{'fast4 abs':<15}{'stored3 med/p90':<17}{'3σ det':<14}{'growth flagged':<16}{'growth resolved':<17}{'shift resolved':<16}{'greedy goal':<14}")
        for col, t in R.get("link_matched", {}).items():
            for k, v in t.items():
                print(f"link, step size matched: {col} {k} = {100*v['rate']:+.1f} pts [{100*v['lo']:+.1f}, {100*v['hi']:+.1f}]")
        for lab, s in R["points"].items():
            print(f"{lab:<10}{(s['median_bound_unit'] or 0):<8.2f}{pct(s['absorbed3']):<15}{pct(s['absorbed_fast4']):<15}{s['stored3_median']:.2f}/{s['stored3_p90']:.2f}{'':<7}{pct(s['det3']):<14}{pct(s['growth_flagged']):<16}{pct(s['growth_resolved_of_flagged']):<17}{pct(s['real_shift_resolved_of_flagged']):<16}{pct(s['greedy_goal']):<14}")
