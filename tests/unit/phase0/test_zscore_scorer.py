"""
tests/unit/phase0/test_zscore_scorer.py
============================================
Covers: standard z-score arithmetic against a hand-built BucketState,
anomaly flagging at the threshold boundary, cold-start suppression for
sparse buckets, the robust_zscore method path, and zero-std safety.
"""
from datetime import datetime, timezone

import pytest

from phase0.bucketing.bucket_key_resolver import BucketKeyResolver
from phase0.constants import PHASE0_SCORING_METHOD_ROBUST_ZSCORE
from phase0.scoring.zscore_scorer import ZScoreScorer
from phase0.types import BucketState

BUCKET_KEY = BucketKeyResolver().resolve("vm-042", "cpu_usage", datetime(2025, 11, 11, 3, 0))


def _state(count, mean, m2, window=None):
    return BucketState(count=count, mean=mean, m2=m2, window=list(window or []))


class TestStandardZScore:
    def test_zscore_matches_hand_computed(self):
        # mean=62, std=3 (m2 = std^2 * count = 9*30=270), value=85
        scorer = ZScoreScorer(min_samples=1)
        state = _state(count=30, mean=62.0, m2=270.0)
        result = scorer.score("vm-042", "cpu_usage", BUCKET_KEY, 85.0, state)
        expected_z = (85.0 - 62.0) / 3.0
        assert result.z_score == pytest.approx(expected_z, rel=1e-6)

    def test_flags_anomaly_above_threshold(self):
        scorer = ZScoreScorer(threshold=3.0, min_samples=1)
        state = _state(count=30, mean=62.0, m2=270.0)  # std=3
        result = scorer.score("vm-042", "cpu_usage", BUCKET_KEY, 85.0, state)  # z ~= 7.67
        assert result.is_anomaly is True

    def test_does_not_flag_within_normal_range(self):
        scorer = ZScoreScorer(threshold=3.0, min_samples=1)
        state = _state(count=30, mean=80.0, m2=1920.0)  # std=8
        result = scorer.score("vm-042", "cpu_usage", BUCKET_KEY, 85.0, state)  # z ~= 0.625
        assert result.is_anomaly is False

    def test_exactly_at_threshold_is_not_anomalous(self):
        # is_anomaly uses strict > threshold, so exactly at the boundary
        # should NOT be flagged.
        scorer = ZScoreScorer(threshold=3.0, min_samples=1)
        state = _state(count=30, mean=0.0, m2=30.0)  # std=1
        result = scorer.score("vm-042", "cpu_usage", BUCKET_KEY, 3.0, state)  # z == 3.0 exactly
        assert result.z_score == pytest.approx(3.0)
        assert result.is_anomaly is False

    def test_zero_std_does_not_crash(self):
        scorer = ZScoreScorer(min_samples=1)
        state = _state(count=10, mean=50.0, m2=0.0)  # perfectly constant so far
        result = scorer.score("vm-042", "cpu_usage", BUCKET_KEY, 999.0, state)
        assert result.z_score == 0.0
        assert result.is_anomaly is False


class TestColdStart:
    def test_sparse_bucket_is_marked_cold_start_and_not_flagged(self):
        scorer = ZScoreScorer(min_samples=5)
        state = _state(count=2, mean=50.0, m2=10.0)  # below min_samples
        result = scorer.score("vm-042", "cpu_usage", BUCKET_KEY, 9999.0, state)
        assert result.cold_start is True
        assert result.is_anomaly is False


class TestRobustMethod:
    def test_robust_method_uses_median_mad(self):
        scorer = ZScoreScorer(method=PHASE0_SCORING_METHOD_ROBUST_ZSCORE, min_samples=1)
        window = [2, 4, 4, 4, 5, 5, 7, 9]
        state = _state(count=len(window), mean=0.0, m2=0.0, window=window)
        result = scorer.score("vm-042", "cpu_usage", BUCKET_KEY, 100.0, state)
        assert result.is_anomaly is True  # 100 is a wild outlier vs this window

    def test_invalid_method_raises_at_construction(self):
        with pytest.raises(ValueError, match="Unknown method"):
            ZScoreScorer(method="not_a_real_method")
