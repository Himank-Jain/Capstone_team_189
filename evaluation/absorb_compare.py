"""
How much of an injected 3-sigma shift is in the stored baseline 14/30/60 days after each strategy's own first alert,
and how many flagged legitimate shifts have stopped being held/alerted by then.  Development data only.
Run: python -m evaluation.absorb_compare <nab_dev|cs_dev>
"""
from __future__ import annotations
import json, multiprocessing as mp, os, sys
DATASET = sys.argv[1]
sys.argv = [sys.argv[0], DATASET, "tune"]
os.environ["EVAL_PROFILE"] = "corestack" if DATASET == "cs_dev" else ""
import numpy as np
from pathlib import Path
from evaluation import final_eval as F
from evaluation.scenarios import END_DAY, SNAPSHOT_DAY
from evaluation.simulate import run

ROOT = Path(__file__).resolve().parents[1]
OFFS = (14, 30, 60)
LABELS = ["adaptive", "longwin", "clip", "rollback", "cusum_r", "frozen", "full_noledger", "full", "dual_noledger", "dual"]


def one(args):
    idx, e, T, th, prep = args
    if not (prep["stable"] and prep["ambient_free"]):
        return None
    scs = F.scenarios(idx, e)
    out = {"source": e.source, "res": {}}
    for lab in LABELS:
        strat, cfg, _ = F.CONFIGS[lab]
        rec = {}
        for name in ("stealth3.0", "benign"):
            sc, corro = scs[name]
            kw = F.kwargs_for(lab, strat, e, T, th)
            if cfg is not None:
                kw["guard_config"] = cfg
                if corro is not None:
                    kw["corroborated"] = corro
            r = run(e, sc, strat, **kw)
            # first alert of this strategy's own alert signal
            sp = [d for d in F.spec(lab, r) if d >= sc.start]
            fa = min(sp) if sp else None
            if fa is None:
                rec[name] = None
                continue
            dd = r.drift_daily
            a = {}
            for o in OFFS:
                i = fa - SNAPSHOT_DAY + o
                a[o] = dd[i] / sc.magnitude if i < len(dd) else None
            held = set(r.held_end_days)
            alerts = set(F.spec(lab, r))
            res_ = {}
            for o in OFFS:
                if fa + o >= END_DAY:
                    res_[o] = None
                else:
                    res_[o] = not any((d in held or d in alerts) for d in range(fa + o, min(fa + o + 14, END_DAY)))
            rec[name] = {"abs": a, "resolved": res_}
        out["res"][lab] = rec
    return out


if __name__ == "__main__":
    E = F.build()
    T = F.tuned_block()
    th = F.thresholds(F.frozen()[f"{F.FAMILY}_dev"], 0.05)
    with mp.Pool(2) as pool:
        prep = pool.map(F._prep, [(i, e, T) for i, e in enumerate(E)], chunksize=2)
        rows = [r for r in pool.map(one, [(i, e, T, th, prep[i]) for i, e in enumerate(E)], chunksize=2) if r]
    summ = {}
    for lab in LABELS:
        s = {}
        for o in OFFS:
            a = [r["res"][lab]["stealth3.0"]["abs"][o] for r in rows if r["res"][lab]["stealth3.0"] and r["res"][lab]["stealth3.0"]["abs"][o] is not None]
            b = [r["res"][lab]["benign"]["resolved"][o] for r in rows if r["res"][lab]["benign"] and r["res"][lab]["benign"]["resolved"][o] is not None]
            s[str(o)] = {"attack_share_median": float(np.median(a)) if a else None, "attack_share_p90": float(np.percentile(a, 90)) if a else None,
                         "n_attack": len(a), "benign_resolved": float(np.mean(b)) if b else None, "n_benign": len(b)}
        summ[lab] = s
    (ROOT / f"docs/patent_evaluation/absorb_compare_{DATASET}.json").write_text(json.dumps(summ, indent=1))
    for lab, s in summ.items():
        print(f"{lab:<15}" + "  ".join(f"+{o}d atk {s[str(o)]['attack_share_median'] if s[str(o)]['attack_share_median'] is None else round(s[str(o)]['attack_share_median'],2)}/{s[str(o)]['attack_share_p90'] if s[str(o)]['attack_share_p90'] is None else round(s[str(o)]['attack_share_p90'],2)} ben {s[str(o)]['benign_resolved'] if s[str(o)]['benign_resolved'] is None else round(s[str(o)]['benign_resolved'],2)}" for o in OFFS))
