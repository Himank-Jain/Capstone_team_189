"""
phase0/bucketing/bucket_key_resolver.py
===========================================
Phase 0 · BucketKeyResolver — the single place that decides "which
bucket does this reading belong to." SRP: this class only resolves keys;
it never touches Redis or scoring logic.
"""

from __future__ import annotations

from datetime import datetime

from phase0.constants import PHASE0_BUCKET_GRANULARITY_HOURS, PHASE0_SPLIT_WEEKDAY_WEEKEND
from phase0.types import BucketKey


class BucketKeyResolver:
    """
    Parameters
    ----------
    granularity_hours:
        Width of each bucket in hours. 1 = hourly (24 buckets/day).
        e.g. 4 = six 4-hour blocks/day. Must evenly divide 24.
    split_weekday_weekend:
        If True, weekday and weekend readings at the same hour go into
        separate buckets (doubling the bucket count).
    """

    def __init__(
        self,
        granularity_hours: int = PHASE0_BUCKET_GRANULARITY_HOURS,
        split_weekday_weekend: bool = PHASE0_SPLIT_WEEKDAY_WEEKEND,
    ) -> None:
        if 24 % granularity_hours != 0:
            raise ValueError(
                f"[BucketKeyResolver] granularity_hours={granularity_hours} must "
                f"evenly divide 24"
            )
        self._granularity_hours = granularity_hours
        self._split_weekday_weekend = split_weekday_weekend

    def resolve(self, vm_id: str, metric_name: str, timestamp: datetime) -> BucketKey:
        """Resolve a SEASONAL (hour + weekday/weekend) bucket key."""
        block_index = timestamp.hour // self._granularity_hours
        is_weekend = timestamp.weekday() >= 5 if self._split_weekday_weekend else None
        return BucketKey(
            vm_id=vm_id,
            metric_name=metric_name,
            hour=block_index,
            is_weekend=is_weekend,
        )

    @staticmethod
    def resolve_global(vm_id: str, metric_name: str) -> BucketKey:
        """Resolve a GLOBAL (non-seasonal, single-bucket) key — used when
        SeasonalityClassifier decides this series has no time-of-day
        pattern worth splitting on."""
        return BucketKey(vm_id=vm_id, metric_name=metric_name, hour=None, is_weekend=None)
