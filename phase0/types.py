"""
phase0/types.py
==================
CAPSTONE-189 · Phase 0 — Adaptive Statistical Baseline.

Self-contained dataclasses. Deliberately does NOT import from
shared/types.py — Phase 0 must remain importable and testable with zero
dependency on phase1/, phase2/, or shared/.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Optional


@dataclass
class MetricPoint:
    """One raw incoming (vm, metric) reading — the unit of work flowing
    through the Phase 0 stream."""
    vm_id: str
    metric_name: str
    timestamp: datetime
    value: float


@dataclass(frozen=True)
class BucketKey:
    """
    Uniquely identifies one rolling baseline. Doubles as the components
    of the Redis key (see RollingBaselineStore).

    hour / is_weekend are both None for a GLOBAL (non-seasonal) baseline
    — i.e. one bucket per (vm_id, metric_name) with no time-of-day split.
    """
    vm_id: str
    metric_name: str
    hour: Optional[int] = None
    is_weekend: Optional[bool] = None

    def is_global(self) -> bool:
        return self.hour is None and self.is_weekend is None


@dataclass
class BucketState:
    """
    The tiny piece of rolling state held per bucket.

    count/mean/m2 are Welford's running sums (O(1) update). `window` is
    the bounded raw-value deque, retained ONLY so the value that ages out
    of the rolling window is known at eviction time — a pure Welford
    accumulator has no way to "un-see" a value on its own. For
    RobustStatsAccumulator (median/MAD), `window` IS the primary state;
    count/mean/m2 are unused (left at defaults) in that mode.
    """
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0
    window: Deque[float] = field(default_factory=deque)

    @property
    def std(self) -> float:
        if self.count < 2:
            return 0.0
        return (self.m2 / self.count) ** 0.5


@dataclass
class ScoreResult:
    """Output of scoring one MetricPoint against its bucket's baseline."""
    vm_id: str
    metric_name: str
    bucket_key: BucketKey
    value: float
    z_score: float
    is_anomaly: bool
    baseline_mean: float
    baseline_std: float
    scored_at: datetime
    cold_start: bool = False  # True if bucket had too few samples to score reliably
