import json, numpy as np
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
R = json.load(open(ROOT / "docs/patent_evaluation/envelope_traces.json"))
TUNED = json.load(open(ROOT / "docs/patent_evaluation/results_raw.json"))["tuned"]
TUNE_SRC = set(TUNED["tuning_sources"])

def arr(tr, lo, hi):
    return np.array([tr[str(d)] for d in range(lo, hi) if str(d) in tr])

def maxrun(x, level):
    best = cur = 0
    for v in x:
        cur = cur + 1 if v > level else 0
        best = max(best, cur)
    return best

def det_threshold(cal, ev, m):
    P = np.percentile(cal, 99)
    return bool((ev > m * P).any())

LEVELS = (0.4, 0.6, 0.8)

def det_envelope(cal, ev, m, g, top=None):
    P = np.percentile(cal, 99) + 1e-9
    top = m if top is None else top
    if (ev > top * P).any():
        return True
    for lam in LEVELS:
        L = int(np.ceil(g * maxrun(cal, lam * P))) + 1
        if maxrun(ev, lam * P * m) >= L:
            return True
    return False

def evaluate(det, rows, T):
    out = {"fp": 0, "n": 0, "tp": {t: 0 for t in T}}
    for r in rows:
        cal = arr(r["tr"]["control"], 30, 90)
        if len(cal) < 20: continue
        out["n"] += 1
        out["fp"] += det(cal, arr(r["tr"]["control"], 90, 220))
        for t in T:
            out["tp"][t] += det(cal, arr(r["tr"][f"atk{t}"], 90, 220))
    return out

if __name__ == "__main__":
    T = (1.0, 1.5, 2.0)
    tune = [r for r in R if r["source"] in TUNE_SRC]
    held = [r for r in R if r["source"] not in TUNE_SRC]
    print(len(tune), len(held))
    for name, rows in (("tune", tune), ("held", held)):
        print("==", name)
        for m in (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0):
            o = evaluate(lambda c, e: det_threshold(c, e, m), rows, T)
            print(f"  thr m={m:<4} FP {o['fp']:>3}/{o['n']}  TP {[o['tp'][t] for t in T]}")
        for m in (1.0, 1.25, 1.5, 2.0):
            for g in (1.0, 1.5, 2.0):
                o = evaluate(lambda c, e: det_envelope(c, e, m, g), rows, T)
                print(f"  env m={m:<4} g={g:<3} FP {o['fp']:>3}/{o['n']}  TP {[o['tp'][t] for t in T]}")
