"""
phase0/scoring/zscore_scorer.py
===================================
Phase 0 · ZScoreScorer — pure scoring logic. SRP: computes a score and a
flag only; never touches Redis or the stream directly (that's
RollingBaselineStore's and AnomalyScoringWorker's job respectively).
"""

from __future__ import annotations

from datetime import datetime, timezone

from phase0.baseline.robust_stats_accumulator import RobustStatsAccumulator
from phase0.constants import (
    PHASE0_MIN_SAMPLES_FOR_SCORING,
    PHASE0_SCORING_METHOD_ROBUST_ZSCORE,
    PHASE0_SCORING_METHOD_ZSCORE,
    PHASE0_ZSCORE_THRESHOLD,
)
from phase0.types import BucketKey, BucketState, ScoreResult


class ZScoreScorer:
    """
    Parameters
    ----------
    method:
        PHASE0_SCORING_METHOD_ZSCORE (mean/std) or
        PHASE0_SCORING_METHOD_ROBUST_ZSCORE (median/MAD). Switching a
        metric's scoring method is a config change via this constructor
        arg, not a code change (Protected Variations).
    threshold:
        |z| beyond this is flagged anomalous.
    min_samples:
        Buckets with fewer than this many observed values are considered
        cold-start and are not scored (ScoreResult.cold_start=True,
        is_anomaly=False) — an early, sparse baseline is not a reliable
        basis for flagging anomalies yet.
    """

    def __init__(
        self,
        method: str = PHASE0_SCORING_METHOD_ZSCORE,
        threshold: float = PHASE0_ZSCORE_THRESHOLD,
        min_samples: int = PHASE0_MIN_SAMPLES_FOR_SCORING,
    ) -> None:
        if method not in (PHASE0_SCORING_METHOD_ZSCORE, PHASE0_SCORING_METHOD_ROBUST_ZSCORE):
            raise ValueError(f"[ZScoreScorer] Unknown method: {method!r}")
        self._method = method
        self._threshold = threshold
        self._min_samples = min_samples

    def score(
        self, vm_id: str, metric_name: str, bucket_key: BucketKey,
        value: float, bucket_state: BucketState,
    ) -> ScoreResult:
        now = datetime.now(timezone.utc)

        if bucket_state.count < self._min_samples:
            return ScoreResult(
                vm_id=vm_id, metric_name=metric_name, bucket_key=bucket_key,
                value=value, z_score=0.0, is_anomaly=False,
                baseline_mean=bucket_state.mean, baseline_std=bucket_state.std,
                scored_at=now, cold_start=True,
            )

        if self._method == PHASE0_SCORING_METHOD_ZSCORE:
            std = bucket_state.std
            z = 0.0 if std == 0.0 else (value - bucket_state.mean) / std
            baseline_mean, baseline_std = bucket_state.mean, std
        else:
            z = RobustStatsAccumulator.robust_z_score(value, bucket_state.window)
            baseline_mean = RobustStatsAccumulator.median(bucket_state.window)
            baseline_std = RobustStatsAccumulator.mad(bucket_state.window, median_value=baseline_mean)

        return ScoreResult(
            vm_id=vm_id, metric_name=metric_name, bucket_key=bucket_key,
            value=value, z_score=z, is_anomaly=abs(z) > self._threshold,
            baseline_mean=baseline_mean, baseline_std=baseline_std,
            scored_at=now, cold_start=False,
        )
