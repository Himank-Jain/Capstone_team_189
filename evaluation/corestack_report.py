import json, numpy as np
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
D = json.load(open(ROOT / "docs/patent_evaluation/corestack_eval_raw.json"))
R, T = D["rows"], D["tuned"]
EV = 60
STR = ["adaptive", "frozen", "longwin", "clip", "cusum", "rollback", "guard_default", "guard_naive", "guard_cal"]

def anyq(a, lo=EV, hi=None): return any(x >= lo and (hi is None or x < hi) for x in a)

def summarize(rows):
    quiet = [r for r in rows if all(not anyq(r["res"][s]["control"]["alerts"]) for s in STR)]
    o = {"series": len(rows), "resources": len({r["resource"] for r in rows}), "quiet_series": len(quiet),
         "quiet_resources": len({r["resource"] for r in quiet}), "strategies": {}}
    for s in STR:
        d = {"control_alert": sum(anyq(r["res"][s]["control"]["alerts"]) for r in rows),
             "control_incident": sum(bool(r["res"][s]["control"]["inc"]) for r in rows)}
        for T_ in (2.0, 3.0, 4.0):
            k = n = 0
            for ramp in (10, 20, 30):
                for r in quiet:
                    n += 1
                    k += anyq(r["res"][s][f"atk_r{ramp}_t{T_}"]["alerts"], EV, EV + ramp + 14)
            d[f"detect_t{T_}"] = [k, n]
        d["poisoned_detect"] = [sum(anyq(r["res"][s]["poisoned"]["alerts"]) for r in quiet), len(quiet)]
        o["strategies"][s] = d
    # calibration validation arm
    qa = [r for r in quiet if not anyq(r["res"]["guard_unvalidated"]["control"]["alerts"])]
    o["calibration_validation"] = {
        "n": len(qa),
        "validated_detected": sum(anyq(r["res"]["guard_cal"]["poisoned"]["alerts"]) for r in qa),
        "unvalidated_detected": sum(anyq(r["res"]["guard_unvalidated"]["poisoned"]["alerts"]) for r in qa),
        "validated_rejected": sum(r["res"]["guard_cal"]["poisoned"]["checks"].get("result") not in ("ok", None) for r in rows),
        "validation_results_control": {},
    }
    res = {}
    for r in rows:
        k = r["res"]["guard_cal"]["control"]["checks"].get("result", "?")
        res[k] = res.get(k, 0) + 1
    o["calibration_validation"]["validation_results_control"] = res
    srcs = {}
    cb = []
    for r in rows:
        c = r["res"]["guard_cal"]["control"]
        srcs[c["src"]] = srcs.get(c["src"], 0) + 1
        if c["bounds"]: cb.append(c["bounds"][1])
    o["bounds"] = {"sources": srcs, "cum_quantiles": [round(float(x), 2) for x in np.quantile(cb, [.1, .25, .5, .75, .9])]}
    return o

if __name__ == "__main__":
    held = [r for r in R if r["heldout"]]
    out = {"margin": T["margin"], "tuning_resources": len(T["tuning_sources"]), "heldout": summarize(held), "all": summarize(R),
           "fleet_bound": T["cohort_stats"]["__global__"]["median_bound"]}
    (ROOT / "docs/patent_evaluation/corestack_eval_results.json").write_text(json.dumps(out, indent=1))
    print("margin", out["margin"], "fleet bound", out["fleet_bound"])
    for lab in ("heldout", "all"):
        o = out[lab]; print("=====", lab, {k: o[k] for k in ("series", "resources", "quiet_series", "quiet_resources")})
        for s, d in o["strategies"].items():
            print(f"{s:<14} ctrl_alert {d['control_alert']:>3} ctrl_inc {d['control_incident']:>3} | detect 2/3/4σ {d['detect_t2.0']}, {d['detect_t3.0']}, {d['detect_t4.0']} | poisoned {d['poisoned_detect']}")
        print(o["calibration_validation"]); print(o["bounds"])
