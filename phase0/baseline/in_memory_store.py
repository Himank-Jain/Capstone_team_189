"""
phase0/baseline/in_memory_store.py
==================================
RollingBaselineStore with a dict instead of Redis. Same state transitions
(it reuses the parent's pure ``_apply_update``), no network, no locking.
Used for offline evaluation and single-process runs.
"""

from __future__ import annotations

from typing import Dict, Optional

from phase0.baseline.rolling_baseline_store import RollingBaselineStore
from phase0.constants import PHASE0_WINDOW_SIZE_DAYS
from phase0.types import BucketKey, BucketState


class InMemoryRollingBaselineStore(RollingBaselineStore):
    def __init__(self, window_size: int = PHASE0_WINDOW_SIZE_DAYS) -> None:
        super().__init__(redis_client=None, window_size=window_size)
        self._states: Dict[BucketKey, BucketState] = {}

    def get_bucket_state(self, bucket_key: BucketKey) -> Optional[BucketState]:
        return self._states.get(bucket_key)

    def update_bucket(self, bucket_key: BucketKey, new_value: float) -> BucketState:
        new_state = self._apply_update(self._states.get(bucket_key) or BucketState(), new_value)
        self._states[bucket_key] = new_state
        return new_state

    def _write_state(self, bucket_key: BucketKey, state: BucketState) -> None:
        self._states[bucket_key] = state

    def copy_states(self) -> Dict[BucketKey, BucketState]:
        return {
            k: BucketState(v.count, v.mean, v.m2, type(v.window)(v.window))
            for k, v in self._states.items()
        }

    def restore_states(self, states: Dict[BucketKey, BucketState]) -> None:
        self._states = {
            k: BucketState(v.count, v.mean, v.m2, type(v.window)(v.window))
            for k, v in states.items()
        }
