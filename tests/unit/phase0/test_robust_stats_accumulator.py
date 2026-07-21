"""
tests/unit/phase0/test_robust_stats_accumulator.py
=======================================================
Covers: median/MAD against hand-computed values, robust z-score formula
correctness, and the divide-by-zero guard for a constant window.
"""
import pytest

from phase0.baseline.robust_stats_accumulator import RobustStatsAccumulator

# median = 5, deviations from median = [3,1,1,1,0,0,2,4] -> median of those = 1
KNOWN_WINDOW = [2, 4, 4, 4, 5, 5, 7, 9]
KNOWN_MEDIAN = 4.5  # even-length window -> average of two middle values (4 and 5)


class TestMedianAndMad:
    def test_median_matches_hand_computed(self):
        assert RobustStatsAccumulator.median(KNOWN_WINDOW) == pytest.approx(KNOWN_MEDIAN)

    def test_mad_matches_hand_computed(self):
        m = RobustStatsAccumulator.median(KNOWN_WINDOW)
        deviations = sorted(abs(x - m) for x in KNOWN_WINDOW)
        expected_mad = (deviations[3] + deviations[4]) / 2  # median of 8 deviations
        assert RobustStatsAccumulator.mad(KNOWN_WINDOW) == pytest.approx(expected_mad)

    def test_empty_window_returns_zero(self):
        assert RobustStatsAccumulator.median([]) == 0.0
        assert RobustStatsAccumulator.mad([]) == 0.0


class TestRobustZScore:
    def test_value_at_median_has_zero_zscore(self):
        m = RobustStatsAccumulator.median(KNOWN_WINDOW)
        z = RobustStatsAccumulator.robust_z_score(m, KNOWN_WINDOW)
        assert z == pytest.approx(0.0, abs=1e-9)

    def test_outlier_produces_large_zscore(self):
        z = RobustStatsAccumulator.robust_z_score(100.0, KNOWN_WINDOW)
        assert abs(z) > 3.0

    def test_constant_window_mad_zero_returns_zero_not_crash(self):
        constant_window = [5.0, 5.0, 5.0, 5.0]
        z = RobustStatsAccumulator.robust_z_score(999.0, constant_window)
        assert z == 0.0  # documented divide-by-zero guard, not a crash
