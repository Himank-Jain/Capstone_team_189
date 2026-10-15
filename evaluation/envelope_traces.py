"""Collect daily cumulative-drift traces (open bounds) for control and stealth attacks."""
import json, multiprocessing as mp
from pathlib import Path
import numpy as np
from evaluation.data import build_entities
from evaluation.runner import eligible
from evaluation.scenarios import Scenario, draw_scenarios
from evaluation.simulate import run
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/external/nab_aws_cloudwatch"
TARGETS = [1.0, 1.5, 2.0, 3.0]

def daily(t):
    d = np.asarray(t["all_day"]); c = np.asarray(t["all_dc"])
    out = {}
    for day in sorted(set(d.tolist())):
        out[int(day)] = float(c[d == day][-1])
    return out

def one(args):
    idx, e = args
    scs = draw_scenarios(idx)
    res = {"id": e.entity_id, "source": e.source, "group": e.group, "tr": {}}
    res["tr"]["control"] = daily(run(e, scs["control"], "guard_probe").traces)
    for T in TARGETS:
        sc = Scenario("attack", "linear", T, ramp_days=60, seed=idx)
        res["tr"][f"atk{T}"] = daily(run(e, sc, "guard_probe").traces)
    sc = scs["benign"]
    res["tr"]["benign"] = daily(run(e, sc, "guard_probe").traces)
    res["benign_meta"] = {"magnitude": sc.magnitude, "cohort": sc.cohort_fraction > 0, "temporary": sc.temporary}
    return res

if __name__ == "__main__":
    E = [e for e in build_entities(DATA, 12) if eligible(e)]
    with mp.Pool(2) as p:
        rows = p.map(one, list(enumerate(E)), chunksize=4)
    (ROOT / "docs/patent_evaluation/envelope_traces.json").write_text(json.dumps(rows))
    print("done", len(rows))
