"""
Design curve of the promotion step cap (development data only).

The statistics cannot tell a persistent attacker level from persistent legitimate growth, so the only lever the system has is
how fast a held entity's stored baseline may move toward the shadow.  This sweeps allow_base (step cap in units of the
calibrated cumulative bound) and reports, after the first alert,
  attack   : share of the injected shift already in the stored baseline at +14/+30/+60 days
  benign   : share of flagged legitimate shifts whose hold has ended by +30/+60 days
Run:  python -m evaluation.cap_sweep <nab_dev|cs_dev>
"""
from __future__ import annotations
import json, multiprocessing as mp, os, random, sys
DATASET = sys.argv[1]
sys.argv = [sys.argv[0], DATASET, "tune"]
os.environ["EVAL_PROFILE"] = "corestack" if DATASET == "cs_dev" else ""
import numpy as np
from pathlib import Path
from evaluation import final_eval as F  # noqa: E402  (reuses builders; reads argv[1] as dataset)
from evaluation.scenarios import END_DAY, EVENT_DAY, SNAPSHOT_DAY, Scenario
from evaluation.simulate import run
from phase0.guard import GuardConfig

ROOT = Path(__file__).resolve().parents[1]
CAPS = [0.25, 0.5, 1.0, 2.0]
OFFS = (14, 30, 60)


def one(args):
    idx, e, T, th, prep = args
    if not (prep["stable"] and prep["ambient_free"]):
        return None
    scs = F.scenarios(idx, e)
    out = {"source": e.source, "res": {}}
    for cap in CAPS:
        cfg = GuardConfig(promotion_mode="ledger", allow_base=cap)
        kw = F.kwargs_for("dual", "guard_dual", e, T, th)
        d = {}
        for name in ("stealth3.0", "benign"):
            sc, corro = scs[name]
            r = run(e, sc, "guard_dual", guard_config=cfg, corroborated=corro, **kw)
            fa = r.first_alert_day
            target = sc.magnitude
            rec = {"fa": fa}
            if fa is not None:
                dd = r.drift_daily
                rec["abs"] = {o: (dd[min(fa - SNAPSHOT_DAY + o, len(dd) - 1)] / target if fa - SNAPSHOT_DAY + o < len(dd) else None) for o in OFFS}
                held = sorted(r.held_end_days)
                last_hold = max([d_ for d_ in held if d_ >= fa], default=None)
                rec["res"] = {o: (not any(fa + o <= d_ for d_ in held)) if fa + o < END_DAY else None for o in OFFS}
            d[name] = rec
        out["res"][str(cap)] = d
    return out


if __name__ == "__main__":
    E = F.build()
    T = F.tuned_block()
    th = F.thresholds(F.frozen()[f"{F.FAMILY}_dev"], 0.05)
    with mp.Pool(2) as pool:
        prep = pool.map(F._prep, [(i, e, T) for i, e in enumerate(E)], chunksize=2)
        rows = [r for r in pool.map(one, [(i, e, T, th, prep[i]) for i, e in enumerate(E)], chunksize=2) if r]
    summ = {}
    for cap in map(str, CAPS):
        a = {o: [r["res"][cap]["stealth3.0"]["abs"][o] for r in rows if r["res"][cap]["stealth3.0"]["fa"] is not None and r["res"][cap]["stealth3.0"]["abs"][o] is not None] for o in OFFS}
        b = {o: [r["res"][cap]["benign"]["res"][o] for r in rows if r["res"][cap]["benign"]["fa"] is not None and r["res"][cap]["benign"]["res"][o] is not None] for o in OFFS}
        summ[cap] = {"attack_absorbed_share_median": {o: float(np.median(v)) if v else None for o, v in a.items()},
                     "attack_absorbed_share_p90": {o: float(np.percentile(v, 90)) if v else None for o, v in a.items()},
                     "benign_hold_ended": {o: (float(np.mean(v)) if v else None) for o, v in b.items()}, "n_attack": len(a[14]), "n_benign": len(b[14])}
    (ROOT / f"docs/patent_evaluation/cap_sweep_{DATASET}.json").write_text(json.dumps(summ, indent=1))
    for cap, s in summ.items():
        print(cap, json.dumps(s))
