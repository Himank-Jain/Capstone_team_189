"""
Cold-start evaluation for cohort seeding.

A "new" entity streams hourly readings from its first hour. After 24 readings
the seeded variant estimates level/scale robustly and seeds its buckets from a
cohort of OTHER source series of the same metric family (leave-source-out).
The unseeded variant is the production behaviour: buckets score only after
PHASE0_MIN_SAMPLES_FOR_SCORING readings each.

Measured per entity
  scoring_start_h  hours until at least half of the next 24 readings are scored
  detect_delay_h   hours from an injected persistent +4 scale-unit level shift
                   (at hour 48) to the first |z| > 3 reading, None if none in 10 days
  false_alert_h    |z| > 3 readings per 100 scored readings on clean data, hours 24-240
Real NAB AWS CloudWatch values; shifts injected.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from evaluation.data import build_entities, _group_of  # noqa: F401
from phase0.baseline.cohort_seeding import (
    CohortShape, build_cohort_shape, robust_level_scale, seed_values,
)
from phase0.baseline.in_memory_store import InMemoryRollingBaselineStore
from phase0.scoring.zscore_scorer import ZScoreScorer
from phase0.types import BucketKey
from datetime import timedelta
from evaluation.data import SIM_START

HOURS = 240
SHIFT_AT = 48
SHIFT = 4.0


def _stream(values: np.ndarray, start_day: int = 0):
    for i in range(HOURS):
        t = SIM_START + timedelta(days=start_day, hours=i)
        yield i, t.hour, t.weekday() >= 5, float(values[i])


def _run(values, seeded: bool, shape: Optional[CohortShape], shift: bool, scale_ref: float):
    store = InMemoryRollingBaselineStore()
    scorer = ZScoreScorer()
    vals = np.array(values[:HOURS], dtype=float)
    if shift:
        vals[SHIFT_AT:] += SHIFT * scale_ref
    scored_flags, alerts = [], []
    for i, hour, wk, v in _stream(vals):
        if seeded and i == 24 and shape is not None:
            level, scale = robust_level_scale(vals[:24])
            for h in range(24):
                for w in (False, True):
                    store.reseed_bucket(BucketKey("e", "m", h, w), seed_values(shape, (h, w), level, scale))
        key = BucketKey("e", "m", hour, wk)
        state = store.get_bucket_state(key)
        if state is not None:
            r = scorer.score("e", "m", key, v, state)
            scored_flags.append(not r.cold_start)
            alerts.append(r.is_anomaly and not r.cold_start)
        else:
            scored_flags.append(False)
            alerts.append(False)
        store.update_bucket(key, v)
    return scored_flags, alerts


def run(data_dir: Path = Path("data/external/nab_aws_cloudwatch"), per_source: int = 2) -> Dict:
    ents = build_entities(data_dir, replicas=per_source)
    by_group: Dict[str, List] = defaultdict(list)
    for e in ents:
        by_group[e.group].append(e)
    sources = {g: sorted({e.source for e in es}) for g, es in by_group.items()}
    rows = []
    for g, es in by_group.items():
        if len(sources[g]) < 3:
            continue
        for e in es:
            cohort = [c for c in es if c.source != e.source]
            hist = []
            for c in {c.source: c for c in cohort}.values():
                h = []
                for d in range(30, 90):
                    for hr in range(24):
                        t = SIM_START + timedelta(days=d, hours=hr)
                        h.append((t.hour, t.weekday() >= 5, float(c.values[d * 24 + hr])))
                hist.append(h)
            shape = build_cohort_shape(hist)
            first = e.values[30 * 24: 30 * 24 + HOURS]  # same weekday alignment as SIM_START (30 % 7 != 0, see below)
            # align start weekday with simulation epoch by taking whole weeks
            start = 28 * 24
            vals = e.values[start:start + HOURS]
            scale_ref = robust_level_scale(e.values[start:start + 24 * 14])[1]
            out = {"entity": e.entity_id, "group": g}
            for name, seeded in (("unseeded", False), ("seeded", True)):
                sc, _ = _run(vals, seeded, shape, False, scale_ref)
                _, al_clean = _run(vals, seeded, shape, False, scale_ref)
                _, al_shift = _run(vals, seeded, shape, True, scale_ref)
                # scoring start: first hour where the next 24 readings are >=50% scored
                start_h = next((i for i in range(0, HOURS - 24) if sum(sc[i:i + 24]) >= 12), None)
                scored_clean = sum(sc[24:])
                fa = 100.0 * sum(al_clean[24:]) / max(1, scored_clean)
                det = next((i - SHIFT_AT for i in range(SHIFT_AT, HOURS) if al_shift[i]), None)
                out[name] = {"scoring_start_h": start_h, "detect_delay_h": det, "false_alerts_per_100": fa}
            rows.append(out)

    def agg(name, key):
        xs = [r[name][key] for r in rows if r[name][key] is not None]
        return {"median": float(statistics.median(xs)) if xs else None, "n": len(xs)}

    res = {"n_entities": len(rows), "rows": rows}
    for name in ("unseeded", "seeded"):
        res[name] = {
            "scoring_start_h": agg(name, "scoring_start_h"),
            "detect_delay_h": agg(name, "detect_delay_h"),
            "detected_k": sum(r[name]["detect_delay_h"] is not None for r in rows),
            "false_alerts_per_100": agg(name, "false_alerts_per_100"),
        }
    return res


if __name__ == "__main__":
    r = run()
    json.dump(r, open("docs/patent_evaluation/cold_start_results.json", "w"), indent=1)
    for k in ("unseeded", "seeded"):
        print(k, json.dumps(r[k]))
    print("entities", r["n_entities"])
