"""
phase0/baseline/welford_accumulator.py
==========================================
Phase 0 · WelfordAccumulator — incremental mean/variance via Welford's
algorithm, extended with a `remove()` counterpart so it supports a true
sliding 30-day window (not just an ever-expanding one).

Standard Welford's algorithm only supports adding points. The `remove()`
method here uses the algebraic inverse of the update step, which is
mathematically valid as long as the value being removed genuinely was
folded in earlier via update() (never remove a value that wasn't added).
"""

from __future__ import annotations


class WelfordAccumulator:
    """Operates on a BucketState's (count, mean, m2) fields in place."""

    @staticmethod
    def update(count: int, mean: float, m2: float, new_value: float) -> tuple[int, float, float]:
        """Fold in one new value. Returns the updated (count, mean, m2)."""
        count += 1
        delta = new_value - mean
        mean += delta / count
        delta2 = new_value - mean
        m2 += delta * delta2
        return count, mean, m2

    @staticmethod
    def remove(count: int, mean: float, m2: float, old_value: float) -> tuple[int, float, float]:
        """
        Remove a value previously folded in via update() — the algebraic
        inverse, used when a value ages out of the rolling window.

        Raises
        ------
        ValueError
            If count would drop below 0, or count==1 (removing the only
            remaining point is handled as a reset to empty instead, to
            avoid a divide-by-zero in the inverse formula).
        """
        if count <= 0:
            raise ValueError("[WelfordAccumulator] Cannot remove from an empty accumulator")
        if count == 1:
            return 0, 0.0, 0.0

        new_count = count - 1
        # Inverse of the update step:
        delta = old_value - mean
        new_mean = mean - delta / new_count
        delta2 = old_value - new_mean
        new_m2 = m2 - delta * delta2
        # Guard against tiny negative floating-point drift on m2
        new_m2 = max(new_m2, 0.0)
        return new_count, new_mean, new_m2

    @staticmethod
    def std(count: int, m2: float) -> float:
        if count < 2:
            return 0.0
        return (m2 / count) ** 0.5
