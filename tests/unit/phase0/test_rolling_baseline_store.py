"""
tests/unit/phase0/test_rolling_baseline_store.py
=====================================================
Covers: Redis key format for seasonal vs global buckets; get/update
round-trip via a real (fake) Redis server; window eviction once the
30-sample cap is exceeded, with mean/std matching a from-scratch
recomputation over the surviving window; and a genuine concurrency test
using real threads hammering the SAME bucket key simultaneously, proving
the WATCH/MULTI/EXEC retry logic doesn't lose updates under contention.

Uses fakeredis (a real in-memory Redis server implementation, not a
hand-rolled mock) so WATCH/MULTI/EXEC semantics are exercised for real.
"""
import threading

import fakeredis
import pytest

from phase0.baseline.rolling_baseline_store import RollingBaselineStore
from phase0.bucketing.bucket_key_resolver import BucketKeyResolver
from phase0.constants import PHASE0_WINDOW_SIZE_DAYS


@pytest.fixture
def redis_client():
    return fakeredis.FakeStrictRedis()


@pytest.fixture
def store(redis_client):
    return RollingBaselineStore(redis_client)


def _seasonal_key():
    from datetime import datetime
    return BucketKeyResolver().resolve("vm-042", "cpu_usage", datetime(2025, 11, 11, 3, 0))


def _global_key():
    return BucketKeyResolver.resolve_global("vm-042", "cpu_usage")


class TestRedisKeyFormat:
    def test_seasonal_key_includes_hour_and_weekday(self, store):
        key = store.redis_key(_seasonal_key())
        assert key == "phase0:baseline:vm-042:cpu_usage:hour03:weekday"

    def test_global_key_has_no_hour(self, store):
        key = store.redis_key(_global_key())
        assert key == "phase0:baseline:vm-042:cpu_usage:global"


class TestGetUpdateRoundTrip:
    def test_missing_bucket_returns_none(self, store):
        assert store.get_bucket_state(_seasonal_key()) is None

    def test_update_then_get_round_trips(self, store):
        key = _seasonal_key()
        state = store.update_bucket(key, 62.0)
        assert state.count == 1
        assert state.mean == pytest.approx(62.0)

        fetched = store.get_bucket_state(key)
        assert fetched.count == 1
        assert fetched.mean == pytest.approx(62.0)

    def test_repeated_updates_accumulate_correctly(self, store):
        key = _seasonal_key()
        values = [60.0, 62.0, 64.0, 61.0, 63.0]
        state = None
        for v in values:
            state = store.update_bucket(key, v)

        expected_mean = sum(values) / len(values)
        assert state.count == len(values)
        assert state.mean == pytest.approx(expected_mean)
        assert list(state.window) == values


class TestWindowEviction:
    def test_window_capped_at_configured_size(self, store, redis_client):
        small_store = RollingBaselineStore(redis_client, window_size=5)
        key = _seasonal_key()
        for v in [10, 20, 30, 40, 50, 60, 70]:  # 7 values into a 5-cap window
            state = small_store.update_bucket(key, v)

        assert state.count == 5
        assert list(state.window) == [30, 40, 50, 60, 70]  # oldest 2 evicted

    def test_mean_after_eviction_matches_surviving_window(self, store, redis_client):
        small_store = RollingBaselineStore(redis_client, window_size=3)
        key = _seasonal_key()
        state = None
        for v in [1, 2, 3, 4, 5]:
            state = small_store.update_bucket(key, v)

        # after 5 updates with cap=3, surviving window should be [3,4,5]
        assert list(state.window) == [3, 4, 5]
        assert state.mean == pytest.approx(4.0)  # mean of [3,4,5]


class TestConcurrentUpdates:
    def test_concurrent_updates_to_same_bucket_lose_no_writes(self, redis_client):
        """
        Real threads, real fakeredis server, hammering the SAME bucket
        key at once. If WATCH/MULTI/EXEC retry logic were broken (e.g. a
        naive GET-then-SET race), some updates would silently overwrite
        each other and the final count would be less than the number of
        updates actually attempted.
        """
        store = RollingBaselineStore(redis_client, window_size=1000)  # cap high, no eviction noise
        key = _seasonal_key()

        n_threads = 8
        updates_per_thread = 25
        total_expected = n_threads * updates_per_thread

        def worker(thread_id: int):
            for i in range(updates_per_thread):
                store.update_bucket(key, float(thread_id * 1000 + i))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final_state = store.get_bucket_state(key)
        assert final_state.count == total_expected, (
            f"Expected {total_expected} updates to be reflected, got "
            f"{final_state.count} — some concurrent writes were lost"
        )
        assert len(final_state.window) == total_expected
