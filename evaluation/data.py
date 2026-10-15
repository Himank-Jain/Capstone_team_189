"""
evaluation/data.py
==================
Real public AWS CloudWatch telemetry (Numenta Anomaly Benchmark, 17 series:
EC2 CPU, EC2 network/disk, ELB requests, RDS CPU) turned into 120-day hourly
entities.

Each source series is only ~14-16 days long, so a long entity is built by
*day resampling*: every simulated day is a real day drawn (with replacement)
from the source series' real days of the same kind (weekday / weekend). Real
values are never altered, so level, noise and daily shape stay real; only the
ordering of days is synthetic. Replicas of the same source series therefore
share a marginal distribution but not a day order.

Fetch the data with:  git clone --depth 1 https://github.com/numenta/NAB
and copy NAB/data/realAWSCloudwatch to data/external/nab_aws_cloudwatch
(scripts/run_patent_evaluation.py does this when the folder is missing).
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np

SIM_START = datetime(2026, 1, 5, tzinfo=timezone.utc)  # a Monday
TOTAL_DAYS = 220


@dataclass
class Entity:
    entity_id: str
    source: str  # source series file stem
    group: str  # cohort: metric family
    replica: int
    values: np.ndarray  # TOTAL_DAYS * 24 hourly values
    hour_scale: float  # median over buckets of the bucket robust scale (first 30 days)
    bucket_scale: np.ndarray = None  # (24 hours x 2 day-types) robust scale of the first 30 days


def _group_of(stem: str) -> str:
    if stem.startswith("ec2_cpu"):
        return "ec2_cpu"
    if stem.startswith("rds_cpu"):
        return "rds_cpu"
    if "disk_write" in stem:
        return "disk_write"
    if "network" in stem.lower():
        return "network_in"
    if stem.startswith("elb"):
        return "elb_requests"
    return "autoscaling"


def _labelled_windows(path: Path) -> List[tuple]:
    """NAB's published anomaly windows for this series (empty if no label file)."""
    label_file = path.parent.parent / "nab_labels_combined_windows.json"
    if not label_file.exists():
        return []
    import json

    labels = json.loads(label_file.read_text())
    wins = labels.get(f"realAWSCloudwatch/{path.name}", [])
    fmt = "%Y-%m-%d %H:%M:%S.%f"
    return [(datetime.strptime(a, fmt), datetime.strptime(b, fmt)) for a, b in wins]


def load_source_days(path: Path) -> List[Dict]:
    """Return real days: {'weekend': bool, 'hours': np.ndarray(24)}.

    Days that overlap an anomaly window labelled by the dataset authors are
    dropped, so the only anomalies in a simulated entity are the ones the
    scenarios inject.
    """
    windows = _labelled_windows(path)
    rows = []
    with open(path, newline="") as fh:
        for rec in csv.DictReader(fh):
            ts = datetime.strptime(rec["timestamp"], "%Y-%m-%d %H:%M:%S")
            rows.append((ts, float(rec["value"])))
    buckets: Dict[tuple, List[float]] = {}
    for ts, v in rows:
        buckets.setdefault((ts.date(), ts.hour), []).append(v)
    days: Dict = {}
    for (d, h), vals in buckets.items():
        days.setdefault(d, {})[h] = float(np.mean(vals))
    out = []
    for d, hours in sorted(days.items()):
        day_start = datetime(d.year, d.month, d.day)
        day_end = day_start + timedelta(days=1)
        if any(a < day_end and b > day_start for a, b in windows):
            continue
        if len(hours) == 24:
            out.append({"weekend": d.weekday() >= 5, "hours": np.array([hours[h] for h in range(24)])})
    return out


def build_entities(data_dir: Path, replicas: int, seed: int = 20261015) -> List[Entity]:
    entities: List[Entity] = []
    for path in sorted(data_dir.glob("*.csv")):
        days = load_source_days(path)
        wk = [d["hours"] for d in days if not d["weekend"]]
        we = [d["hours"] for d in days if d["weekend"]]
        if len(wk) < 5 or len(we) < 2:
            continue
        for rep in range(replicas):
            rng = random.Random(f"{seed}-{path.stem}-{rep}")
            chunks = []
            for day in range(TOTAL_DAYS):
                weekend = (SIM_START + timedelta(days=day)).weekday() >= 5
                pool = we if weekend else wk
                chunks.append(pool[rng.randrange(len(pool))])
            values = np.concatenate(chunks)
            values = _smooth(values, rng)
            entities.append(Entity(
                entity_id=f"{path.stem}#{rep}",
                source=path.stem,
                group=_group_of(path.stem),
                replica=rep,
                values=values,
                hour_scale=_residual_scale(values[: 30 * 24]),
                bucket_scale=_bucket_scales(values[: 30 * 24]),
            ))
    return entities


SMOOTHING = 0.2  # jitter sd as a fraction of the bucket scale


def _smooth(values: np.ndarray, rng: random.Random) -> np.ndarray:
    """Smoothed bootstrap: add small continuous noise to resampled readings.
    Without it, repeated real days make bucket medians jump in steps (or not
    move at all), which is an artefact of resampling ~10 real days, not a
    property of telemetry."""
    scales = _bucket_scales(values[: 30 * 24])
    nprng = np.random.default_rng(rng.randrange(2**32))
    out = values.astype(float).copy()
    for i in range(len(out)):
        day, hour = divmod(i, 24)
        weekend = int((SIM_START + timedelta(days=day)).weekday() >= 5)
        out[i] += nprng.normal(0.0, SMOOTHING * scales[hour, weekend])
    return out


def _residual_scale(first30: np.ndarray) -> float:
    """Entity scale unit: the median, over the 48 (hour, weekday/weekend)
    buckets, of the robust scale of each bucket's first-30-day window. This is
    the same quantity the drift guard divides by (s_snap), so one scale unit
    in a scenario equals one unit of D."""
    from phase0.guard.drift_guard import robust_scale

    by_bucket: Dict[tuple, List[float]] = {}
    for i, v in enumerate(first30):
        day, hour = divmod(i, 24)
        weekend = (SIM_START + timedelta(days=day)).weekday() >= 5
        by_bucket.setdefault((hour, weekend), []).append(float(v))
    scales = [robust_scale(w) for w in by_bucket.values() if len(w) >= 5]
    return float(np.median(scales))


def _bucket_scales(first30: np.ndarray) -> np.ndarray:
    """Robust scale of every (hour, weekday/weekend) bucket over the first 30
    days, shape (24, 2). An attacker who mimics the entity's variance shifts
    each bucket in proportion to its own scale."""
    from phase0.guard.drift_guard import robust_scale

    by_bucket: Dict[tuple, List[float]] = {}
    for i, v in enumerate(first30):
        day, hour = divmod(i, 24)
        weekend = (SIM_START + timedelta(days=day)).weekday() >= 5
        by_bucket.setdefault((hour, int(weekend)), []).append(float(v))
    out = np.zeros((24, 2))
    fallback = float(np.median([robust_scale(w) for w in by_bucket.values() if len(w) >= 5]))
    for h in range(24):
        for t in range(2):
            w = by_bucket.get((h, t), [])
            out[h, t] = robust_scale(w) if len(w) >= 5 else fallback
    return out
