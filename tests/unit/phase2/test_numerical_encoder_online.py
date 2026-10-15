"""Online standardisation for metrics the checkpoint has never seen."""
import random

import pytest

from phase2.encoding.numerical_encoder import NumericalEncoder

STATS = {"cpu": (50.0, 10.0)}


def test_in_vocab_metric_unchanged_by_online_mode():
    a = NumericalEncoder(STATS)
    b = NumericalEncoder(STATS, online_oov_stats=True)
    assert a.encode("cpu", 70.0) == pytest.approx(b.encode("cpu", 70.0))


def test_default_keeps_raw_passthrough_for_oov():
    enc = NumericalEncoder(STATS)
    assert enc.encode("queue", 12345.0) == pytest.approx(12345.0, rel=1e-6)


def test_online_oov_is_neutral_then_standardised():
    enc = NumericalEncoder(STATS, online_oov_stats=True, online_min_count=8)
    rng = random.Random(1)
    first = [enc.encode("queue", 5e5 + rng.gauss(0, 1e4)) for _ in range(8)]
    assert all(v == 0.0 for v in first)
    later = [enc.encode("queue", 5e5 + rng.gauss(0, 1e4)) for _ in range(200)]
    assert abs(sum(later) / len(later)) < 0.5
    assert 0.5 < (sum(v * v for v in later) / len(later)) ** 0.5 < 1.6
    assert enc.encode("queue", 5e5 + 8e4) > 4.0  # a clear excursion stands out
