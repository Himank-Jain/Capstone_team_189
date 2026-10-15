"""
Build the second fresh CoreStack set from series that were never used in development or in the first fresh evaluation.

Inputs   cs_candidates_runs.pkl : {(resourceId, metric): (category, run_start_date, hourly_values)}, the longest run of
                                 complete hourly days of every (resource, metric) pair in the raw daily-collection dump
                                 (built on the owner's machine; one 'average' value per hour, duplicated hours overwritten
                                 by the later document).
Selection rule (fixed before any detector was run on these series):
  1. the resource is not one of the 62 resources in corestack_series_90d.pkl / corestack_series_100d.pkl;
  2. take the latest Monday-aligned 90-day window inside the run;
  3. keep the series if evaluation.runner.eligible() accepts it (non-degenerate scale; the same filter as every other set);
  4. keep at most 3 series per resource, ordered by sha1(resourceId|metric), so that no resource dominates.
Output   data/external/corestack/corestack_series_fresh2_90d.pkl in the same format as corestack_series_90d.pkl.
"""
import datetime as dt
import hashlib
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

os.environ["EVAL_PROFILE"] = "corestack90"
from evaluation.data import Entity, _bucket_scales, _residual_scale  # noqa: E402
from evaluation.runner import eligible  # noqa: E402

cand = pickle.load(open(sys.argv[1], "rb"))
used = {k[0].lower() for n in ("90d", "100d") for k in pickle.load(open(f"data/external/corestack/corestack_series_{n}.pkl", "rb"))}
per = defaultdict(list)
for (rid, m), (cat, start, vals) in cand.items():
    if rid.lower() in used:
        continue
    n = len(vals) // 24
    last = dt.date.fromisoformat(start) + dt.timedelta(n - 90)
    while last.weekday() != 0:
        last -= dt.timedelta(1)
    off = (last - dt.date.fromisoformat(start)).days
    if off < 0:
        continue
    v = vals[off * 24:(off + 90) * 24]
    e = Entity(entity_id=m, source=rid.lower(), group=f"{cat}:{m}", replica=0, values=v,
               hour_scale=_residual_scale(v[:720]), bucket_scale=_bucket_scales(v[:720]))
    if not eligible(e):
        continue
    h = hashlib.sha1(f"{rid}|{m}".encode()).hexdigest()
    per[rid.lower()].append((h, rid, m, cat, last.isoformat(), v))
out = {}
for rid, items in per.items():
    for h, r, m, cat, st, v in sorted(items)[:3]:
        out[(r, m, cat)] = {"start": st, "values": np.asarray(v, float)}
pickle.dump(out, open("data/external/corestack/corestack_series_fresh2_90d.pkl", "wb"))
print("resources", len({k[0].lower() for k in out}), "series", len(out))
