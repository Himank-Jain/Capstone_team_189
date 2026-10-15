import random

import pytest

from phase0.baseline.cohort_seeding import build_cohort_shape, robust_level_scale, seed_values


def _history(level, amp, seed):
    rng = random.Random(seed)
    out = []
    for d in range(14):
        for h in range(24):
            out.append((h, d % 7 >= 5, level + amp * (1 if 9 <= h <= 17 else -1) + rng.gauss(0, amp * 0.2)))
    return out


def test_robust_level_scale_ignores_outlier():
    lvl, sc = robust_level_scale([10, 11, 9, 10, 12, 10, 9, 1000])
    assert 9 <= lvl <= 11 and sc < 5


def test_shape_is_dimensionless_across_levels():
    shape = build_cohort_shape([_history(10, 2, 1), _history(5000, 400, 2)])
    assert shape.n_entities == 2
    assert shape.offsets[(12, False)] > shape.offsets[(3, False)]


def test_seed_values_follow_target_level_and_scale():
    shape = build_cohort_shape([_history(10, 2, 1), _history(40, 8, 2)])
    vals = seed_values(shape, (12, False), level=1000.0, scale=50.0)
    assert len(vals) == 5 and min(vals) < max(vals)
    assert 900 < sum(vals) / 5 < 1300  # centred near the target's own level, daytime high


def test_empty_cohort_raises():
    with pytest.raises(ValueError):
        build_cohort_shape([[(0, False, 1.0)]])
