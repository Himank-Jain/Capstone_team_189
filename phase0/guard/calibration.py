"""
phase0/guard/calibration.py
===========================
Per-entity bound calibration with validation (the calibration period can
itself be poisoned, so it is checked before it is trusted).

bound = margin * 99th percentile of D observed on a validated benign period
(margin 1.25 by default; evaluation/runner.py tunes it on held-out entities).

Validation checks on a calibration trace:
 1. periods with an open or confirmed alert are excluded;
 2. split-half trend must stay below 0.5 sigma;
 3. the entity's 95th percentile D must not exceed the cohort's 95th
    percentile, otherwise the cohort bound is used instead;
 4. the bound is capped at 1.5x the cohort median bound.

If validation fails or there is too little data, the entity falls back to the
default bound (1.0 sigma windowed, 2.0 sigma cumulative).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

MARGIN = 1.25  # default; evaluation tunes it on held-out entities (see evaluation/runner.py)
TREND_LIMIT_SIGMA = 0.5
COHORT_CAP = 1.5
MIN_TRACE = 20
# Noise floor for any bound, in scale units. The median of ~30 readings per bucket wanders by about
# 1.25*sigma/sqrt(30) = 0.23 sigma on its own; a bound below ~2 such standard errors would hold on
# sampling noise. Real CoreStack series that are flat or mostly zero produced own-p99 drift of exactly 0
# and therefore a bound of 0 (every reading held); the floor prevents that.
MIN_BOUND = 0.5


@dataclass
class BoundCalibration:
    windowed: float
    cumulative: float
    source: str  # "entity" | "cohort" | "default"
    checks: dict = field(default_factory=dict)


def _percentile(values: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q))


def calibrate_bounds(
    d_windowed: Sequence[float],
    d_cumulative: Sequence[float],
    alert_flags: Optional[Sequence[bool]] = None,
    signed_drift: Optional[Sequence[float]] = None,
    cohort_p95: Optional[Tuple[float, float]] = None,
    cohort_median_bound: Optional[Tuple[float, float]] = None,
    default: Tuple[float, float] = (1.0, 2.0),
    margin: float = MARGIN,
    floor: float = MIN_BOUND,
) -> BoundCalibration:
    """Compute and validate bounds from calibration traces.

    ``alert_flags[i]`` marks samples that fall in a period with an open or
    confirmed alert. ``signed_drift`` is the signed baseline shift from the
    snapshot, used for the split-half trend check.
    """
    checks: dict = {}
    n = len(d_windowed)
    keep = [i for i in range(n) if not (alert_flags and alert_flags[i])]
    checks["excluded_alert_samples"] = n - len(keep)
    if len(keep) < MIN_TRACE:
        checks["result"] = "too little clean data"
        return BoundCalibration(default[0], default[1], "default", checks)

    if signed_drift is not None:
        sd = [signed_drift[i] for i in keep]
        half = len(sd) // 2
        trend = abs(statistics.median(sd[half:]) - statistics.median(sd[:half]))
        checks["split_half_trend"] = trend
        if trend >= TREND_LIMIT_SIGMA:
            checks["result"] = "trend in calibration period"
            return BoundCalibration(default[0], default[1], "default", checks)

    w = [d_windowed[i] for i in keep]
    c = [d_cumulative[i] for i in keep]
    bound_w = margin * _percentile(w, 99)
    bound_c = margin * _percentile(c, 99)
    source = "entity"

    if cohort_p95 is not None:
        own_p95 = (_percentile(w, 95), _percentile(c, 95))
        checks["own_p95"] = own_p95
        if own_p95[0] > cohort_p95[0] or own_p95[1] > cohort_p95[1]:
            if cohort_median_bound is not None:
                bound_w, bound_c = cohort_median_bound
                source = "cohort"
                checks["cohort_check"] = "above cohort p95, cohort bound used"

    if cohort_median_bound is not None:
        cap_w = COHORT_CAP * cohort_median_bound[0]
        cap_c = COHORT_CAP * cohort_median_bound[1]
        if bound_w > cap_w or bound_c > cap_c:
            checks["capped"] = True
        bound_w = min(bound_w, cap_w)
        bound_c = min(bound_c, cap_c)

    if bound_w < floor or bound_c < floor:
        checks["floored"] = True
    bound_w, bound_c = max(bound_w, floor), max(bound_c, floor)
    checks["result"] = "ok"
    return BoundCalibration(bound_w, bound_c, source, checks)
