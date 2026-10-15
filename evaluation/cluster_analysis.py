"""
Series-level analysis of the guard evaluation.

The 203 entities are resampled from 17 real series, so they are not independent.
This script (a) reports how many distinct series each result rests on, (b) gives
cluster-bootstrap 95% intervals that resample SERIES rather than entities, and
(c) shows what real growth costs over time: the share of benign-growth runs still
alerting in each period after the shift, per strategy.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from evaluation.runner import COMPARE, EVENT_DAY, END_DAY, _any_in

OUT = Path("docs/patent_evaluation")
STRATS = ["adaptive", "frozen", "longwin", "clip", "cusum", "rollback", "guard_cal"]
PERIODS = [(EVENT_DAY, EVENT_DAY + 30), (EVENT_DAY + 30, EVENT_DAY + 60), (EVENT_DAY + 60, EVENT_DAY + 90), (EVENT_DAY + 90, END_DAY)]


def boot(groups, stat, n=4000, seed=0):
    """groups: dict series -> list of 0/1; resample series with replacement."""
    rng = np.random.default_rng(seed)
    keys = list(groups)
    vals = []
    for _ in range(n):
        pick = rng.choice(len(keys), len(keys))
        k = sum(sum(groups[keys[i]]) for i in pick)
        m = sum(len(groups[keys[i]]) for i in pick)
        vals.append(k / m if m else np.nan)
    lo, hi = np.nanpercentile(vals, [2.5, 97.5])
    return [round(100 * lo, 1), round(100 * hi, 1)]


def main():
    raw = json.load(open(OUT / "results_raw.json"))
    rows = [r for r in raw["rows"] if r["heldout"]]
    quiet = [r for r in rows if all(not _any_in(r["scen"][s]["control"]["alerts"], EVENT_DAY) for s in COMPARE)]
    res = {
        "n_series_total": len({r["source"] for r in raw["rows"]}),
        "n_series_heldout": len({r["source"] for r in rows}),
        "n_series_quiet": len({r["source"] for r in quiet}),
        "n_entities_heldout": len(rows), "n_entities_quiet": len(quiet),
        "series_per_group_quiet": {},
        "strategies": {},
    }
    g = defaultdict(set)
    for r in quiet:
        g[r["group"]].add(r["source"])
    res["series_per_group_quiet"] = {k: len(v) for k, v in g.items()}
    for s in STRATS:
        att, ctl, ben = defaultdict(list), defaultdict(list), defaultdict(list)
        for r in rows:
            ctl[r["source"]].append(int(_any_in(r["scen"][s]["control"]["alerts"], EVENT_DAY)))
        for r in quiet:
            a = r["scen"][s]["attack"]
            att[r["source"]].append(int(_any_in(a["alerts"], EVENT_DAY, EVENT_DAY + r["attack_meta"]["ramp"] + 30)))
            ben[r["source"]].append(int(_any_in(r["scen"][s]["benign"]["alerts"], EVENT_DAY)))
        per = {}
        for lo, hi in PERIODS:
            per[f"{lo}-{hi}"] = sum(int(_any_in(r["scen"][s]["benign"]["alerts"], lo, hi)) for r in quiet)
        res["strategies"][s] = {
            "attack_alerted": {"k": sum(map(sum, att.values())), "n": len(quiet), "series_ci95": boot(att, None)},
            "control_alert": {"k": sum(map(sum, ctl.values())), "n": len(rows), "series_ci95": boot(ctl, None)},
            "benign_flagged": {"k": sum(map(sum, ben.values())), "n": len(quiet), "series_ci95": boot(ben, None)},
            "benign_still_alerting_by_period": per,
        }
    json.dump(res, open(OUT / "cluster_results.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "strategies"}))
    for s, v in res["strategies"].items():
        print(f"{s:10s} atk {v['attack_alerted']['k']}/{v['attack_alerted']['n']} {v['attack_alerted']['series_ci95']} | ctl {v['control_alert']['k']}/{v['control_alert']['n']} {v['control_alert']['series_ci95']} | benign {v['benign_flagged']['k']} {v['benign_flagged']['series_ci95']} | by period {list(v['benign_still_alerting_by_period'].values())}")


if __name__ == "__main__":
    main()
