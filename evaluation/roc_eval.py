"""
Operating-curve comparison: detection of stealth attacks vs false-alert rate, swept over each method's threshold.

Methods and their only free threshold:
  guard_cal  validated per-entity drift bound; swept over the margin m          (strategy-specific alert = guard incident)
  guard_fleet fleet-median bound scaled by s                                    (guard incident)
  cusum      CUSUM on z of the day-mean residual; swept over decision threshold h (strategy-specific alert = CUSUM alarm)
Only strategy-specific alerts are counted, on entities whose control run raises no ordinary z-flag alert after
the event, so every method is judged on the alerts it adds, not on shared ambient alerts.
Attacks: linear ramp over 60 days to T in {1,2,3} sigma (non-adaptive). Detection = alert within ramp+30 days.
"""
from __future__ import annotations
import json, multiprocessing as mp
from pathlib import Path
from evaluation.data import build_entities
from evaluation.runner import eligible
from evaluation.scenarios import EVENT_DAY, Scenario, draw_scenarios
from evaluation.simulate import run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/external/nab_aws_cloudwatch"
TUNED = json.load(open(ROOT / "docs/patent_evaluation/results_raw.json"))["tuned"]
MARGINS = [2.0, 3.0, 4.5, 7.0, 10.0, 15.0]
HS = [3.0, 5.0, 8.0, 12.0, 18.0, 30.0]
FLEET = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
TARGETS = [1.0, 2.0, 3.0]


def spec(r, kind):
    return sorted(r.incident_days if kind == "guard" else r.cusum_days)


def one(args):
    idx, e = args
    cs = TUNED["cohort_stats"]
    base = cs["__global__"]["median_bound"]
    scs = draw_scenarios(idx)
    atk = {T: Scenario("attack", "linear", T, ramp_days=60, seed=idx) for T in TARGETS}
    out = {"id": e.entity_id, "source": e.source, "heldout": e.source not in set(TUNED["tuning_sources"]), "res": {}}
    ctrl_adaptive = run(e, scs["control"], "adaptive")
    out["ambient_flags"] = sorted(d for d in ctrl_adaptive.flag_days if d >= EVENT_DAY)
    for m in MARGINS:
        d = {}
        for name, sc in [("control", scs["control"])] + [(f"atk{T}", atk[T]) for T in TARGETS]:
            d[name] = spec(run(e, sc, "guard_cal", default_bounds=base, margin=m, cohort_stats=cs.get(e.group)), "guard")
        out["res"][f"guard_cal_m{m}"] = d
    for sc_ in FLEET:
        d = {}
        b = (base[0] * sc_, base[1] * sc_)
        for name, sc in [("control", scs["control"])] + [(f"atk{T}", atk[T]) for T in TARGETS]:
            d[name] = spec(run(e, sc, "guard_default", default_bounds=b), "guard")
        out["res"][f"guard_fleet_s{sc_}"] = d
    for h in HS:
        d = {}
        for name, sc in [("control", scs["control"])] + [(f"atk{T}", atk[T]) for T in TARGETS]:
            d[name] = spec(run(e, sc, "cusum", cusum_h=h), "cusum")
        out["res"][f"cusum_h{h}"] = d
    return out


if __name__ == "__main__":
    E = [e for e in build_entities(DATA, 12) if eligible(e)]
    with mp.Pool(2) as p:
        rows = p.map(one, list(enumerate(E)), chunksize=2)
    (ROOT / "docs/patent_evaluation/roc_raw.json").write_text(json.dumps(rows))
    print("done", len(rows))
