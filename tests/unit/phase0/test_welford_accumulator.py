"""
tests/unit/phase0/test_welford_accumulator.py
==================================================
Covers: update() matches hand-computed population mean/std on a classic
textbook dataset; remove() is a true algebraic inverse of update() (state
after add-then-remove matches state as if the value was never added);
edge cases (removing the last remaining point, removing from empty).
"""
import pytest

from phase0.baseline.welford_accumulator import WelfordAccumulator

# Classic dataset: population mean=5, population std=2
KNOWN_VALUES = [2, 4, 4, 4, 5, 5, 7, 9]
KNOWN_MEAN = 5.0
KNOWN_STD = 2.0


class TestUpdateMatchesKnownStats:
    def test_mean_and_std_match_hand_computed_values(self):
        count, mean, m2 = 0, 0.0, 0.0
        for v in KNOWN_VALUES:
            count, mean, m2 = WelfordAccumulator.update(count, mean, m2, v)

        assert mean == pytest.approx(KNOWN_MEAN, rel=1e-9)
        assert WelfordAccumulator.std(count, m2) == pytest.approx(KNOWN_STD, rel=1e-9)
        assert count == len(KNOWN_VALUES)

    def test_single_value_has_zero_std(self):
        count, mean, m2 = WelfordAccumulator.update(0, 0.0, 0.0, 42.0)
        assert mean == 42.0
        assert WelfordAccumulator.std(count, m2) == 0.0


class TestRemoveIsExactInverse:
    def test_add_then_remove_matches_never_added_state(self):
        # State after adding all of KNOWN_VALUES except the last one:
        count_a, mean_a, m2_a = 0, 0.0, 0.0
        for v in KNOWN_VALUES[:-1]:
            count_a, mean_a, m2_a = WelfordAccumulator.update(count_a, mean_a, m2_a, v)

        # State after adding ALL values, then removing the last one:
        count_b, mean_b, m2_b = 0, 0.0, 0.0
        for v in KNOWN_VALUES:
            count_b, mean_b, m2_b = WelfordAccumulator.update(count_b, mean_b, m2_b, v)
        count_b, mean_b, m2_b = WelfordAccumulator.remove(count_b, mean_b, m2_b, KNOWN_VALUES[-1])

        assert count_b == count_a
        assert mean_b == pytest.approx(mean_a, abs=1e-9)
        assert m2_b == pytest.approx(m2_a, abs=1e-9)

    def test_remove_the_only_point_resets_to_empty(self):
        count, mean, m2 = WelfordAccumulator.update(0, 0.0, 0.0, 42.0)
        count, mean, m2 = WelfordAccumulator.remove(count, mean, m2, 42.0)
        assert (count, mean, m2) == (0, 0.0, 0.0)

    def test_remove_from_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            WelfordAccumulator.remove(0, 0.0, 0.0, 42.0)

    def test_sliding_window_of_fixed_size_matches_direct_computation(self):
        # Simulate a rolling window of size 3 over a longer stream, and
        # confirm the incrementally-maintained mean matches a direct
        # from-scratch computation over the current window at each step.
        stream = [10, 20, 30, 40, 50, 60]
        window_size = 3
        count, mean, m2 = 0, 0.0, 0.0
        window = []

        for v in stream:
            count, mean, m2 = WelfordAccumulator.update(count, mean, m2, v)
            window.append(v)
            if len(window) > window_size:
                oldest = window.pop(0)
                count, mean, m2 = WelfordAccumulator.remove(count, mean, m2, oldest)

            expected_mean = sum(window) / len(window)
            assert mean == pytest.approx(expected_mean, abs=1e-9)
