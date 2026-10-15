import json, numpy as np
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
R = json.load(open(ROOT / "docs/patent_evaluation/pareto_raw.json"))
EV, END, TAIL = 90, 220, 14
LABELS = list(R[0]["res"])

def q(x, p): return float(np.percentile(x, p)) if x else None

def summarize(rows):
    # entities whose control run is quiet post-event under every strategy (common basis, as before)
    quiet = [r for r in rows if all(not any(d >= EV for d in r["res"][s]["control"]["alerts"]) for s in LABELS)]
    out = {"n": len(rows), "n_quiet": len(quiet), "strategies": {}}
    for s in LABELS:
        d = {}
        d["control_alert"] = sum(any(a >= EV for a in r["res"][s]["control"]["alerts"]) for r in rows)
        for name in ("attack", "stealth1.0", "stealth2.0", "local4.0", "local6.0"):
            xs = [r["res"][s][name] for r in quiet]
            det = [x for x in xs if x["first_alert_day"] is not None]
            disp = [x["first_alert_drift"] for x in det]
            d[name] = {"detected": len(det), "n": len(xs),
                       "silent_displacement_median": q(disp, 50), "silent_displacement_p90": q(disp, 90),
                       "silent_displacement_max": max(disp) if disp else None,
                       "missed_final_drift_median": q([x["drift_final"] for x in xs if x["first_alert_day"] is None], 50)}
        xs = [r["res"][s]["benign_iso"] for r in quiet]
        fl = [x for x in xs if x["alerts"] and any(a >= EV for a in x["alerts"])]
        spans = [max(a for a in x["alerts"] if a >= EV) - min(a for a in x["alerts"] if a >= EV) + 1 for x in fl]
        d["benign"] = {"flagged": len(fl), "n": len(xs),
                       "alert_days_median": q([sum(1 for a in x["alerts"] if a >= EV) for x in fl], 50),
                       "span_days_median": q(spans, 50),
                       "unresolved_at_end": sum(1 for x in fl if x["tail_alert"] or x["tail_held"])}
        d["benign_held_days_median"] = q([x["held_days"] for x in fl], 50)
        out["strategies"][s] = d
    return out

if __name__ == "__main__":
    held = [r for r in R if r["heldout"]]
    res = {"heldout": summarize(held), "all": summarize(R)}
    (ROOT / "docs/patent_evaluation/pareto_results.json").write_text(json.dumps(res, indent=1))
    for lab in ("heldout", "all"):
        o = res[lab]; print("=====", lab, "n", o["n"], "quiet", o["n_quiet"])
        print(f"{'strategy':<18}{'ctrl':>5} | atk det/disp med,p90,max | stealth2 det/disp med,p90,max | stealth1 det/disp med | benign flagged/unresolved/span")
        for s, d in o["strategies"].items():
            a, b, c, bn = d["attack"], d["stealth2.0"], d["stealth1.0"], d["benign"]
            f = lambda v: "-" if v is None else f"{v:.2f}"
            print(f"{s:<18}{d['control_alert']:>5} | {a['detected']:>3}/{a['n']} {f(a['silent_displacement_median'])},{f(a['silent_displacement_p90'])},{f(a['silent_displacement_max'])} | "
                  f"{b['detected']:>3}/{b['n']} {f(b['silent_displacement_median'])},{f(b['silent_displacement_p90'])},{f(b['silent_displacement_max'])} | "
                  f"{c['detected']:>3}/{c['n']} {f(c['silent_displacement_median'])} | local4 {d['local4.0']['detected']}/{d['local4.0']['n']} disp {f(d['local4.0']['silent_displacement_median'])} local6 {d['local6.0']['detected']}/{d['local6.0']['n']} | {bn['flagged']}/{bn['unresolved_at_end']}/{bn['span_days_median']}")
