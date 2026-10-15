"""
phase0/baseline/cohort_seeding.py
=================================
Cohort cold start. A new entity has empty hour x day-type buckets and, until
each holds PHASE0_MIN_SAMPLES_FOR_SCORING readings (about five days for a
weekday bucket), its readings are not scored at all.

Seeding borrows the *shape* of a cohort of similar entities (same metric
family) and the new entity's own *level and scale*, estimated robustly from its
first day of readings. Each bucket is seeded with a few synthetic readings
``level + scale * (shape_bucket + residual_quantile)`` so scoring can start
after one day. Real readings then fold in and push the seed out of the
30-reading window.

The cohort contributes only dimensionless numbers (bucket offsets in units of
the entity's own robust scale and a residual distribution); no raw values from
other entities enter the new entity's baseline.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

BucketIdx = Tuple[int, bool]  # (hour, is_weekend)


def robust_level_scale(values: Sequence[float]) -> Tuple[float, float]:
    """Median and 1.4826 x MAD (floored so a flat series cannot give 0)."""
    vals = [float(v) for v in values]
    med = statistics.median(vals)
    mad = statistics.median(abs(v - med) for v in vals)
    scale = 1.4826 * mad
    if scale <= 0:
        scale = (statistics.pstdev(vals) if len(vals) > 1 else 0.0) or 1.0
    return med, scale


@dataclass
class CohortShape:
    offsets: Dict[BucketIdx, float]      # bucket median offset, in entity scale units
    residual_quantiles: List[float]      # residual distribution, in entity scale units
    n_entities: int


def build_cohort_shape(
    histories: Iterable[Sequence[Tuple[int, bool, float]]],
    quantiles: Sequence[float] = (0.02, 0.25, 0.5, 0.75, 0.98),
) -> CohortShape:
    """``histories``: one sequence of (hour, is_weekend, value) per cohort entity."""
    per_bucket: Dict[BucketIdx, List[float]] = {}
    residuals: List[float] = []
    n = 0
    for hist in histories:
        hist = list(hist)
        if len(hist) < 48:
            continue
        level, scale = robust_level_scale([v for _, _, v in hist])
        buckets: Dict[BucketIdx, List[float]] = {}
        for h, w, v in hist:
            buckets.setdefault((h, w), []).append((v - level) / scale)
        for key, vals in buckets.items():
            med = statistics.median(vals)
            per_bucket.setdefault(key, []).append(med)
            residuals.extend(v - med for v in vals)
        n += 1
    if n == 0:
        raise ValueError("cohort has no usable history")
    offsets = {k: statistics.median(v) for k, v in per_bucket.items()}
    residuals.sort()
    qs = [residuals[min(len(residuals) - 1, int(q * len(residuals)))] for q in quantiles]
    return CohortShape(offsets=offsets, residual_quantiles=qs, n_entities=n)


def seed_values(shape: CohortShape, bucket: BucketIdx, level: float, scale: float) -> List[float]:
    off = shape.offsets.get(bucket, 0.0)
    return [level + scale * (off + q) for q in shape.residual_quantiles]
