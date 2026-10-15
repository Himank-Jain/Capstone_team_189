"""
Summarise evaluation/deck_protocol.py:  python -m evaluation.deck_protocol_report <dataset>

Populations (all entities are real CoreStack series that pass runner.eligible; STABLE = its own data stays within one hour-scale unit
of its reference level after the event; AMBIENT-FREE = the plain adaptive baseline raises no ordinary flag after the event; FLAT = no
variation at all before the event, so any additive change is visible and a detector's rate there says nothing about telemetry):
  varying  stable, ambient-free, not flat     <- headline
  all      stable, ambient-free
  flat     stable, ambient-free, flat
Every rate carries a 95% interval from a bootstrap over resources (sources), not over series.

"detected" counts any alert (baselines) or incident (guards) in the 30 drift days. "detected | control quiet" counts it only for entities whose
control run (no injection) raised nothing for the same strategy, so that a strategy that alerts on everything cannot score by false alarms.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

DATASET = sys.argv[1]
OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"
D = json.load(open(OUT / f"deckproto_{DATASET}.json"))
ROWS = D["rows"]
EV = 60
END = 100 if DATASET == "cs_dev" else 90
DRIFT_END = min(EV + 30, END)
PAYLOAD_START = EV + 20
PROFILES = ("linear", "stepped", "noise_masked")
TOTALS = {"R1": (0.15, 0.30, 0.60, 0.90), "R3": (1.0, 2.0, 3.0, 4.0)}  # same constants as evaluation/deck_protocol.py
OFFSET = {"R1": 0, "R2": 1, "R3": 2}
BENIGN = (0.25, 0.5, 1.0, 2.0, 3.0)
rng = np.random.default_rng(0)
STRATS = ["adaptive", "w2x", "slow5", "robust", "slow5_robust", "guard", "guard_trig"]
NAMES = {"adaptive": "Adaptive baseline (reference)", "w2x": "Longer window (2x)", "slow5": "Slower rate (5x lower; 150-reading window)",
         "robust": "Robust median and MAD", "slow5_robust": "Slower rate plus robust median", "guard": "Guard, bound trigger only",
         "guard_trig": "Guard, bound trigger plus robust sequential trigger"}


def pops():
    clean = [r for r in ROWS if r["stable"] and r["ambient_free"]]
    return {"varying": [r for r in clean if not r["flat"]], "all": clean, "flat": [r for r in clean if r["flat"]]}


def boot(items, reps=2000):
    """items: list of (source, 0/1 or value). Mean with a cluster bootstrap over sources."""
    if not items:
        return None
    by = {}
    for s, v in items:
        by.setdefault(s, []).append(v)
    keys = list(by)
    pt = float(np.mean([v for _, v in items]))
    bs = []
    for _ in range(reps):
        pick = rng.choice(len(keys), len(keys))
        bs.append(np.mean([x for i in pick for x in by[keys[i]]]))
    return {"rate": pt, "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)), "n": len(items), "sources": len(keys)}


def fmt(x):
    return "-" if x is None else f"{100 * x['rate']:5.1f}% ({100 * x['lo']:.0f}-{100 * x['hi']:.0f}) n={x['n']}"


def first_in(cell, lo, hi):
    xs = [x for x in cell["spec"] if lo <= x < hi]
    return min(xs) if xs else None


def quiet(r, st):
    return first_in(r["res"]["control"][st], EV, END) is None


def attacked(r, st, name):
    return first_in(r["res"][name][st], EV, DRIFT_END) is not None


def main():
    summary = {"dataset": DATASET, "trigger": D["trigger"], "default_bound": D["default_bound"], "populations": {}}
    for pname, rows in pops().items():
        if not rows:
            continue
        S = summary["populations"][pname] = {"n_entities": len(rows), "n_sources": len({r["source"] for r in rows})}
        print(f"\n######## population: {pname}  ({len(rows)} series, {S['n_sources']} resources)")
        for fam in ("R1", "R2", "R3"):
            names = [f"{fam}_{p}" for p in PROFILES]
            print(f"\n-- {fam}: {len(rows) * 3} injected 30-day drifts (3 profiles x {len(rows)} series)")
            print(f"{'strategy':<56} {'detected':>26} {'detected | control quiet':>28} {'median delay':>13} {'drift at end':>13}")
            S[fam] = {}
            for st in STRATS:
                det = [(r["source"], int(attacked(r, st, n))) for r in rows for n in names]
                detq = [(r["source"], int(attacked(r, st, n))) for r in rows if quiet(r, st) for n in names]
                delays = [first_in(r["res"][n][st], EV, DRIFT_END) - EV for r in rows for n in names if attacked(r, st, n)]
                disp = [min(r["res"][n][st]["drift_final"], 99.0) for r in rows for n in names]  # flat series have scale 0: capped, never a headline
                S[fam][st] = {"detected": boot(det), "detected_control_quiet": boot(detq), "median_delay": (float(np.median(delays)) if delays else None),
                              "median_drift": float(np.median(disp)), "mean_drift": float(np.mean(disp))}
                print(f"{NAMES[st]:<56} {fmt(S[fam][st]['detected']):>26} {fmt(S[fam][st]['detected_control_quiet']):>28} {('%.0f d' % np.median(delays)) if delays else '-':>13} {np.median(disp):>12.2f}s")
            if fam in TOTALS:
                print(f"   {fam} by 30-day total (units of the entity's hour scale), pooled over profiles, detected | control quiet:")
                S[f"{fam}_by_total"] = {}
                for ti, tot in enumerate(TOTALS[fam]):
                    line = []
                    for st in ("adaptive", "robust", "guard", "guard_trig"):
                        items = [(r["source"], int(attacked(r, st, f"{fam}_{p}"))) for r in rows if quiet(r, st) for pi, p in enumerate(PROFILES) if (r["idx"] + pi + OFFSET[fam]) % 4 == ti]
                        b = boot(items)
                        S[f"{fam}_by_total"].setdefault(str(tot), {})[st] = b
                        line.append(f"{st}:{fmt(b).split(' (')[0].strip()}")
                    print(f"      total {tot:<5} " + "  ".join(line))
                print(f"   {fam} median detection delay (days from the event) by 30-day total, among detected:")
                S[f"{fam}_delay_by_total"] = {}
                for ti, tot in enumerate(TOTALS[fam]):
                    line = []
                    for st in ("adaptive", "robust", "guard", "guard_trig"):
                        dl = [first_in(r["res"][f"{fam}_{p}"][st], EV, DRIFT_END) - EV for r in rows for pi, p in enumerate(PROFILES)
                              if (r["idx"] + pi + OFFSET[fam]) % 4 == ti and attacked(r, st, f"{fam}_{p}")]
                        S[f"{fam}_delay_by_total"].setdefault(str(tot), {})[st] = (float(np.median(dl)) if dl else None)
                        line.append(f"{st}:{('%.0f d' % np.median(dl)) if dl else '-'}(n={len(dl)})")
                    print(f"      total {tot:<5} " + "  ".join(line))
        # ---- false flags --------------------------------------------------------------------------------------------
        print("\n-- false flags (flagged = alert for a baseline, incident/hold for the guard)")
        S["control"], S["benign"] = {}, {}
        for st in STRATS:
            c = [(r["source"], int(first_in(r["res"]["control"][st], EV, END) is not None)) for r in rows]
            bn = [(r["source"], int(first_in(r["res"]["benign"][st], EV, END) is not None)) for r in rows]
            S["control"][st], S["benign"][st] = boot(c), boot(bn)
            print(f"{NAMES[st]:<56} control {fmt(S['control'][st]):>26}   benign shifts {fmt(S['benign'][st]):>26}")
        S["benign_sub"] = {}
        for st in STRATS:
            S["benign_sub"][st] = boot([(r["source"], int(first_in(r["res"]["benign_sub"][st], EV, END) is not None)) for r in rows])
        print("   permanent shift of half the entity's own calibrated cumulative bound (inside what the guard tolerates):  "
              + "   ".join(f"{st}:{fmt(S['benign_sub'][st]).split(' (')[0].strip()}" for st in ("adaptive", "robust", "guard", "guard_trig")))
        print("   benign shifts by size (adaptive / guard / guard_trig):")
        S["benign_by_size"] = {}
        for bi, mag in enumerate(BENIGN):
            line = []
            for st in ("adaptive", "guard", "guard_trig"):
                items = [(r["source"], int(first_in(r["res"]["benign"][st], EV, END) is not None)) for r in rows if r["idx"] % 5 == bi]
                b = boot(items)
                S["benign_by_size"].setdefault(str(mag), {})[st] = b
                line.append(f"{st}:{fmt(b).split(' (')[0].strip()}")
            print(f"      {mag:<5} " + "  ".join(line))
        # ---- stress: adaptive attacker ------------------------------------------------------------------------------
        print("\n-- adaptive attacker (ramps to 95% of the cumulative bound over 20 days, then a payload for the rest of the run)")
        S["adaptive_attacker"] = {}
        for scn, label in (("adaptive_attacker", "payload 3 units"), ("adaptive_attacker_1", "payload 1 unit")):
            S["adaptive_attacker"][scn] = {}
            for st in ("adaptive", "robust", "guard", "guard_trig"):
                def pay_detected(r, scn=scn, st=st):
                    c = r["res"][scn][st]
                    return int(first_in(c, PAYLOAD_START, END) is not None or c["held_end"] or any(x >= PAYLOAD_START for x in c["collapsed"]))
                b = boot([(r["source"], pay_detected(r)) for r in rows])
                mx = [min(r["res"][scn][st]["drift_max"], 99.0) for r in rows]
                S["adaptive_attacker"][scn][st] = {"payload_detected": b, "median_max_drift": float(np.median(mx))}
                print(f"{label:<16} {NAMES[st]:<56} payload detected (alert, incident, or held at the end) {fmt(b):>26}  median max displacement {np.median(mx):.2f}")
        S["median_cumulative_bound"] = float(np.median([r["bc"] for r in rows]))
        print(f"   median calibrated cumulative bound of these entities: {S['median_cumulative_bound']:.2f}")
        # ---- stress: poisoned calibration ---------------------------------------------------------------------------
        print("\n-- attacker present during calibration (from day 35)")
        infl_v, infl_u = [], []
        for r in rows:
            clean_b = r["res"]["control"]["guard"]["bounds"]
            pb = r["res"]["poisoned"]["guard"]["bounds"]
            ub = r["res"]["poisoned"]["guard_unvalidated"]["bounds"]
            if clean_b and pb and ub and clean_b[1] > 0:
                infl_v.append(pb[1] / clean_b[1] - 1.0)
                infl_u.append(ub[1] / clean_b[1] - 1.0)
        det = {st: boot([(r["source"], int(first_in(r["res"]["poisoned"][st], EV, END) is not None)) for r in rows]) for st in ("adaptive", "guard", "guard_trig", "guard_unvalidated")}
        S["poisoned"] = {"inflation_validated_median": float(np.median(infl_v)), "inflation_unvalidated_median": float(np.median(infl_u)),
                         "inflation_validated_mean": float(np.mean(infl_v)), "inflation_unvalidated_mean": float(np.mean(infl_u)), "n": len(infl_v), "detected_after": det}
        print(f"   cumulative-bound inflation vs the clean calibration (n={len(infl_v)}): with validation median {100 * np.median(infl_v):+.0f}% (mean {100 * np.mean(infl_v):+.0f}%), "
              f"without {100 * np.median(infl_u):+.0f}% (mean {100 * np.mean(infl_u):+.0f}%)")
        for st, b in det.items():
            print(f"   detected after: {st:<18} {fmt(b)}")
        # ---- growth and migration: promotion and incidents ----------------------------------------------------------
        print("\n-- permanent benign shifts (growth / migration): what the hold does next")
        S["growth"] = {}
        for st in ("guard", "guard_trig"):
            cells = [r["res"]["benign"][st] for r in rows if first_in(r["res"]["benign"][st], EV, END) is not None]
            prom = [c for c in cells if c["promotions"]]
            released = [c for c in cells if not c["held_end"]]
            S["growth"][st] = {"flagged": len(cells), "of": len(rows), "promoted_at_least_once": len(prom), "released_by_end": len(released),
                               "median_days_to_first_promotion": (float(np.median([min(c["promotions"]) - c["first"] for c in prom])) if prom else None),
                               "median_flag_days": float(np.median([len([x for x in c["flag_days"] if x >= EV]) for c in cells])) if cells else None,
                               "median_incidents": float(np.median([len([x for x in c["spec"] if x >= EV]) for c in cells])) if cells else None,
                               "held_at_end": len(cells) - len(released)}
            g = S["growth"][st]
            print(f"   {st}: flagged {g['flagged']} of {g['of']}; at least one promotion step {g['promoted_at_least_once']}; released (not held) by the end {g['released_by_end']}; "
                  f"median days to first promotion {g['median_days_to_first_promotion']}; median flag-days {g['median_flag_days']}, median incidents {g['median_incidents']}")
    (OUT / f"deckproto_summary_{DATASET}.json").write_text(json.dumps(summary, indent=1, default=float))


if __name__ == "__main__":
    main()
