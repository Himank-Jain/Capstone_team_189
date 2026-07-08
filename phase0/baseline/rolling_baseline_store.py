"""
phase0/baseline/rolling_baseline_store.py
=============================================
Phase 0 · RollingBaselineStore — the Redis-backed persistence layer.
Information Expert for "what is this bucket's current state," and the
only class in Phase 0 that knows the Redis key format.

Concurrency note
-----------------
Multiple AnomalyScoringWorker processes may update the SAME bucket key
concurrently (e.g. two partitions both happen to touch vm-042:cpu_usage
around the same time, or a rebalance briefly overlaps). A naive
read-modify-write (GET, compute new state in Python, SET) has a race:
two workers could both read the same old state and one update would
silently overwrite the other's.

This is solved with Redis's optimistic-locking pattern: WATCH the key,
build the new state from the watched value, then commit via a pipelined
MULTI/EXEC. If another client modified the key in between, EXEC returns
None (aborted) and we retry from scratch. This is the standard redis-py
pattern for read-modify-write and does not require a Lua script.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Optional

from phase0.baseline.welford_accumulator import WelfordAccumulator
from phase0.constants import PHASE0_REDIS_KEY_PREFIX, PHASE0_WINDOW_SIZE_DAYS
from phase0.types import BucketKey, BucketState

logger_obj = logging.getLogger(__name__)

MAX_WATCH_RETRIES = 100
# Randomized exponential backoff between WATCH retries, so competing
# threads/processes don't immediately re-collide on the same key over
# and over (the classic "thundering herd" failure mode of optimistic
# locking under sustained contention on one exact key). In the intended
# production topology, work is partitioned by (vm_id, metric_name) so
# this level of contention on one key should be rare — this backoff
# exists as a defensive property of the store itself, not because
# heavy same-key contention is expected to be the normal case.
BACKOFF_BASE_SECONDS = 0.001
BACKOFF_CAP_SECONDS = 0.05


class RollingBaselineStore:
    """
    Parameters
    ----------
    redis_client:
        Any redis-py-compatible client (real `redis.Redis`, or a fake
        like `fakeredis.FakeRedis` for testing — both implement the same
        WATCH/pipeline interface, which is all this class depends on).
    key_prefix:
        Redis key namespace. Kept separate from Phase 2's `entity:*` keys
        by design (see Phase 0 Directory Structure doc, Section 6).
    window_size:
        Max samples retained per bucket before the oldest is evicted.
    """

    def __init__(
        self,
        redis_client,
        key_prefix: str = PHASE0_REDIS_KEY_PREFIX,
        window_size: int = PHASE0_WINDOW_SIZE_DAYS,
    ) -> None:
        self._redis = redis_client
        self._key_prefix = key_prefix
        self._window_size = window_size

    # ── Key formatting ───────────────────────────────────────────────────

    def redis_key(self, bucket_key: BucketKey) -> str:
        if bucket_key.is_global():
            return f"{self._key_prefix}:{bucket_key.vm_id}:{bucket_key.metric_name}:global"

        parts = [self._key_prefix, bucket_key.vm_id, bucket_key.metric_name, f"hour{bucket_key.hour:02d}"]
        if bucket_key.is_weekend is True:
            parts.append("weekend")
        elif bucket_key.is_weekend is False:
            parts.append("weekday")
        return ":".join(parts)

    # ── Serialization ────────────────────────────────────────────────────

    @staticmethod
    def _serialize(state: BucketState) -> str:
        return json.dumps({
            "count": state.count,
            "mean": state.mean,
            "m2": state.m2,
            "window": list(state.window),
        })

    @staticmethod
    def _deserialize(raw: bytes | str) -> BucketState:
        payload = json.loads(raw)
        return BucketState(
            count=payload["count"],
            mean=payload["mean"],
            m2=payload["m2"],
            window=list(payload["window"]),
        )

    # ── Reads ────────────────────────────────────────────────────────────

    def get_bucket_state(self, bucket_key: BucketKey) -> Optional[BucketState]:
        raw = self._redis.get(self.redis_key(bucket_key))
        if raw is None:
            return None
        return self._deserialize(raw)

    # ── Writes ───────────────────────────────────────────────────────────

    def update_bucket(self, bucket_key: BucketKey, new_value: float) -> BucketState:
        """
        Fold `new_value` into the bucket's rolling state, evicting the
        oldest value if the window would exceed `window_size`. Returns
        the POST-update state. Race-safe under concurrent callers via
        WATCH/MULTI/EXEC with retry.
        """
        redis_key = self.redis_key(bucket_key)

        for attempt in range(MAX_WATCH_RETRIES):
            with self._redis.pipeline() as pipe:
                try:
                    pipe.watch(redis_key)
                    raw = pipe.get(redis_key)
                    current = self._deserialize(raw) if raw is not None else BucketState()

                    new_state = self._apply_update(current, new_value)

                    pipe.multi()
                    pipe.set(redis_key, self._serialize(new_state))
                    pipe.execute()  # raises WatchError if the key changed underneath us
                    return new_state
                except Exception as exc:  # redis.WatchError in real redis-py
                    if type(exc).__name__ != "WatchError":
                        raise
                    logger_obj.debug(
                        "[RollingBaselineStore] WATCH conflict on %s, retry %d/%d",
                        redis_key, attempt + 1, MAX_WATCH_RETRIES,
                    )
                    backoff = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** attempt))
                    time.sleep(random.uniform(0, backoff))
                    continue

        raise RuntimeError(
            f"[RollingBaselineStore] Failed to update {redis_key} after "
            f"{MAX_WATCH_RETRIES} WATCH retries — unexpectedly high contention"
        )

    def _apply_update(self, state: BucketState, new_value: float) -> BucketState:
        """Pure state-transition logic, factored out so it's testable
        without touching Redis at all."""
        count, mean, m2 = WelfordAccumulator.update(state.count, state.mean, state.m2, new_value)
        window = list(state.window)
        window.append(new_value)

        if len(window) > self._window_size:
            oldest = window.pop(0)
            count, mean, m2 = WelfordAccumulator.remove(count, mean, m2, oldest)

        return BucketState(count=count, mean=mean, m2=m2, window=window)