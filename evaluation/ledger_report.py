import json, numpy as np
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
R = json.load(open(ROOT / "docs/patent_evaluation/ledger_raw.json"))
END = 220
def med(x): return float(np.median(x)) if x else None
def frac(k, n): return f"{k}/{n}"

def summarize(rows):
    out = {}
    for v in rows[0]["res"]:
        d = {}
        d["control_false_incident"] = frac(sum(bool(r["res"][v]["control"]["inc"]) for r in rows), len(rows))
        for scen, sel in (("benign_iso_no_change", lambda r: not r["benign_meta"]["change"]),
                          ("benign_iso_change", lambda r: r["benign_meta"]["change"]),
                          ("benign_iso_all", lambda r: True)):
            xs = [r["res"][v]["benign_iso"] for r in rows if sel(r)]
            inc = [x for x in xs if x["inc"]]
            res = [x["resolved_day"] - x["first_inc"] for x in inc if x["resolved_day"] is not None]
            d[scen] = {"n": len(xs), "with_incident": len(inc), "resolved": len(res),
                       "resolved_within_30d": sum(r_ <= 30 for r_ in res), "resolved_within_60d": sum(r_ <= 60 for r_ in res),
                       "still_held_at_end": sum(x["still_held"] for x in inc),
                       "median_days_to_resolve": med(res), "median_held_days": med([x["held_days"] for x in inc]),
                       "median_incidents": med([len(x["inc"]) for x in inc])}
        xs = [r["res"][v]["benign_iso_op"] for r in rows]
        inc = [x for x in xs if x["inc"]]
        res = [x["resolved_day"] - x["first_inc"] for x in inc if x["resolved_day"] is not None]
        d["benign_iso_operator"] = {"with_incident": len(inc), "resolved": len(res), "median_days_to_resolve": med(res)}
        for scen, key in (("attack_isolated", "attack"), ("attack_cohort_wide", "cattack")):
            xs = [(r, r["res"][v][key]) for r in rows]
            tgt = lambda r: r["attack_meta"]["target"]
            inc = [(r, x) for r, x in xs if x["inc"]]
            d[scen] = {"n": len(xs), "detected_incident": len(inc),
                       "absorbed_ge_half_target": sum(x["drift_final"] >= 0.5 * tgt(r) for r, x in xs),
                       "absorbed_ge_80pct_target": sum(x["drift_final"] >= 0.8 * tgt(r) for r, x in xs),
                       "median_final_drift_over_target": med([x["drift_final"] / tgt(r) for r, x in xs]),
                       "median_held_days": med([x["held_days"] for _, x in inc]),
                       "incidents_median": med([len(x["inc"]) for _, x in inc])}
        out[v] = d
    return out

if __name__ == "__main__":
    held = [r for r in R if r["heldout"]]
    res = {"heldout": summarize(held), "all": summarize(R), "n_heldout": len(held), "n_all": len(R)}
    (ROOT / "docs/patent_evaluation/ledger_results.json").write_text(json.dumps(res, indent=1))
    for lab in ("heldout", "all"):
        print("=====", lab, res["n_" + ("heldout" if lab == "heldout" else "all")])
        for v, d in res[lab].items():
            print(v, "ctrl", d["control_false_incident"])
            for k in ("benign_iso_no_change", "benign_iso_change", "benign_iso_operator", "attack_isolated", "attack_cohort_wide"):
                print("   ", k, json.dumps(d[k]))
