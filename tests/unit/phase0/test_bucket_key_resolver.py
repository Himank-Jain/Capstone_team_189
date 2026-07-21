"""
tests/unit/phase0/test_bucket_key_resolver.py
==================================================
Covers: hourly bucket assignment, coarser granularity blocks, weekday/
weekend split (Monday=0 convention matching Python's datetime.weekday()),
the global (non-seasonal) key path, and the granularity validation guard.
"""
from datetime import datetime

import pytest

from phase0.bucketing.bucket_key_resolver import BucketKeyResolver
from phase0.types import BucketKey


class TestHourlyResolution:
    def test_hour_maps_directly_to_block_at_granularity_1(self):
        resolver = BucketKeyResolver(granularity_hours=1, split_weekday_weekend=False)
        ts = datetime(2025, 11, 11, 15, 30)  # 3:30pm -> hour block 15
        key = resolver.resolve("vm-042", "cpu_usage", ts)
        assert key.hour == 15

    def test_coarser_granularity_groups_hours_into_blocks(self):
        resolver = BucketKeyResolver(granularity_hours=4, split_weekday_weekend=False)
        # hours 12,13,14,15 should all fall in block index 3 (12//4=3)
        for hour in (12, 13, 14, 15):
            key = resolver.resolve("vm-042", "cpu_usage", datetime(2025, 11, 11, hour, 0))
            assert key.hour == 3

    def test_invalid_granularity_raises(self):
        with pytest.raises(ValueError, match="evenly divide 24"):
            BucketKeyResolver(granularity_hours=5)


class TestWeekdayWeekendSplit:
    def test_monday_is_weekday(self):
        resolver = BucketKeyResolver(split_weekday_weekend=True)
        ts = datetime(2025, 11, 10, 3, 0)  # a Monday
        key = resolver.resolve("vm-042", "cpu_usage", ts)
        assert key.is_weekend is False

    def test_saturday_is_weekend(self):
        resolver = BucketKeyResolver(split_weekday_weekend=True)
        ts = datetime(2025, 11, 15, 3, 0)  # a Saturday
        key = resolver.resolve("vm-042", "cpu_usage", ts)
        assert key.is_weekend is True

    def test_split_disabled_gives_none(self):
        resolver = BucketKeyResolver(split_weekday_weekend=False)
        ts = datetime(2025, 11, 15, 3, 0)
        key = resolver.resolve("vm-042", "cpu_usage", ts)
        assert key.is_weekend is None


class TestKeyIdentity:
    def test_same_inputs_produce_equal_keys(self):
        resolver = BucketKeyResolver()
        ts = datetime(2025, 11, 11, 3, 7)
        k1 = resolver.resolve("vm-042", "cpu_usage", ts)
        k2 = resolver.resolve("vm-042", "cpu_usage", ts)
        assert k1 == k2  # frozen dataclass -> value equality

    def test_different_vm_produces_different_key(self):
        resolver = BucketKeyResolver()
        ts = datetime(2025, 11, 11, 3, 7)
        k1 = resolver.resolve("vm-042", "cpu_usage", ts)
        k2 = resolver.resolve("vm-999", "cpu_usage", ts)
        assert k1 != k2


class TestGlobalKey:
    def test_global_key_has_no_hour_or_weekend(self):
        key = BucketKeyResolver.resolve_global("vm-042", "cpu_usage")
        assert key.hour is None
        assert key.is_weekend is None
        assert key.is_global() is True

    def test_seasonal_key_is_not_global(self):
        resolver = BucketKeyResolver()
        key = resolver.resolve("vm-042", "cpu_usage", datetime(2025, 11, 11, 3, 0))
        assert key.is_global() is False
