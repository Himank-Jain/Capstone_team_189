"""
phase0/baseline/robust_stats_accumulator.py
===============================================
Phase 0 · RobustStatsAccumulator — median/MAD (median absolute deviation)
baseline, for metrics where a few extreme spikes would distort a
mean/std-based baseline (e.g. bursty I/O counters).

Unlike WelfordAccumulator, median/MAD have no O(1) incremental update —
computing them requires the full sorted window. This is an intentional,
documented cost/accuracy tradeoff: correctness over raw speed for metrics
where robustness to outliers matters more than update latency.
"""

from __future__ import annotations

import statistics
from typing import Sequence

from phase0.constants import PHASE0_ROBUST_Z_CONSTANT


class RobustStatsAccumulator:
    """Stateless — operates directly on a bucket's raw value window."""

    @staticmethod
    def median(window: Sequence[float]) -> float:
        if not window:
            return 0.0
        return statistics.median(window)

    @staticmethod
    def mad(window: Sequence[float], median_value: float | None = None) -> float:
        """Median Absolute Deviation: median(|x_i - median(x)|)."""
        if not window:
            return 0.0
        m = median_value if median_value is not None else RobustStatsAccumulator.median(window)
        deviations = [abs(x - m) for x in window]
        return statistics.median(deviations)

    @staticmethod
    def robust_z_score(value: float, window: Sequence[float]) -> float:
        """
        Consistency-corrected robust z-score:
            0.6745 * (value - median) / mad

        Returns 0.0 if mad == 0 (e.g. a perfectly constant series so far)
        to avoid a divide-by-zero — a constant baseline with a genuinely
        different new value is better handled by the caller checking
        `value != median` separately if that edge case matters, rather
        than this method raising.
        """
        if not window:
            return 0.0
        m = RobustStatsAccumulator.median(window)
        mad_value = RobustStatsAccumulator.mad(window, median_value=m)
        if mad_value == 0.0:
            return 0.0
        return PHASE0_ROBUST_Z_CONSTANT * (value - m) / mad_value
