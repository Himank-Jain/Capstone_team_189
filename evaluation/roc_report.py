import json, numpy as np
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
R = json.load(open(ROOT / "docs/patent_evaluation/roc_raw.json"))
for _name in ("gov", "cgov"):
    _g = ROOT / f"docs/patent_evaluation/roc_{_name}_raw.json"
    if _g.exists():  # governor sweeps rerun with the corrected reference scale replace the first one
        G = {r["id"]: r for r in json.load(open(_g))}
        for r in R:
            r["res"] = {k: v for k, v in r["res"].items() if not k.startswith(_name + "_")}
            r["res"].update({k: v for k, v in G[r["id"]]["res"].items() if k.startswith(_name + "_")})
EV = 90
FAM = {"guard_cal": "guard (per-entity)", "guard_fleet": "guard (fleet bound)", "cusum": "CUSUM", "gov": "governor (bounds + CUSUM trigger)", "cgov": "snapshot-CUSUM trigger only"}

def has(a, lo=EV, hi=None): return any(x >= lo and (hi is None or x < hi) for x in a)

def curve(rows):
    quiet = [r for r in rows if not r["ambient_flags"]]
    out = {}
    for label in R[0]["res"]:
        fam = label.rsplit("_", 1)[0] if label.startswith(("guard_cal", "guard_fleet")) else label.split("_")[0]
        fpr = sum(has(r["res"][label]["control"]) for r in quiet) / len(quiet)
        tpr = {T: sum(has(r["res"][label][f"atk{T}"], EV, EV + 90) for r in quiet) / len(quiet) for T in (1.0, 2.0, 3.0)}
        out[label] = {"family": fam, "fpr": fpr, "tpr": tpr, "n": len(quiet)}
    return out

def at_fpr(c, fam, level):
    cands = [v for v in c.values() if v["family"] == fam and v["fpr"] <= level]
    if not cands: return None
    best = max(cands, key=lambda v: (v["tpr"][2.0], v["tpr"][1.0]))
    return best

if __name__ == "__main__":
    res = {}
    for lab, rows in (("heldout", [r for r in R if r["heldout"]]), ("all", R)):
        c = curve(rows)
        res[lab] = {"curve": c, "matched": {}}
        print("=====", lab, "quiet", next(iter(c.values()))["n"])
        for label, v in c.items():
            print(f"  {label:<18} FPR {v['fpr']:.2f}  TPR 1σ {v['tpr'][1.0]:.2f} 2σ {v['tpr'][2.0]:.2f} 3σ {v['tpr'][3.0]:.2f}")
        for level in (0.05, 0.10, 0.20, 0.30):
            row = {}
            for fam in ("guard_cal", "guard_fleet", "cusum", "gov", "cgov"):
                b = at_fpr(c, fam, level)
                row[fam] = None if b is None else {"fpr": b["fpr"], **{str(k): x for k, x in b["tpr"].items()}}
            res[lab]["matched"][str(level)] = row
            print(f"  matched FPR<={level}:", {k: (None if v is None else (round(v['fpr'], 2), round(v['2.0'], 2), round(v['1.0'], 2))) for k, v in row.items()})
    (ROOT / "docs/patent_evaluation/roc_results.json").write_text(json.dumps(res, indent=1))
