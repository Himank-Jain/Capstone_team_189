"""
phase0/workers/anomaly_scoring_worker.py
=============================================
Phase 0 · AnomalyScoringWorker — the Controller (GRASP): orchestrates the
full per-point cycle: read -> resolve bucket -> fetch baseline -> score
-> publish -> update baseline.

process_point() contains all the interesting logic and takes no stream
dependency at all, so it's directly unit-testable with a synthetic
MetricPoint and a real (or fakeredis-backed) RollingBaselineStore —
run_async() is a thin loop around it for production use.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from typing import Callable, List, Optional

from phase0.baseline.rolling_baseline_store import RollingBaselineStore
from phase0.bucketing.bucket_key_resolver import BucketKeyResolver
from phase0.guard.drift_guard import DriftGuard, GuardAction
from phase0.scoring.zscore_scorer import ZScoreScorer
from phase0.seasonality.seasonality_classifier import SeasonalityClassifier
from phase0.streaming.base_stream_reader import BaseStreamReader
from phase0.types import MetricPoint, ScoreResult

logger_obj = logging.getLogger(__name__)


class AnomalyScoringWorker:
    """
    Parameters
    ----------
    stream_reader:
        Any BaseStreamReader implementation (DIP).
    baseline_store:
        RollingBaselineStore instance (real Redis or fakeredis-backed).
    bucket_resolver / seasonality_classifier / scorer:
        Injected collaborators — all independently testable/mockable.
    on_score:
        Callback invoked with each ScoreResult. Never allowed to crash
        the worker loop — an exception here is logged and processing
        continues (matches Phase 2's IngestionPipeline "never crash on
        bad input" principle).
    """

    def __init__(
        self,
        stream_reader: BaseStreamReader,
        baseline_store: RollingBaselineStore,
        on_score: Callable[[ScoreResult], None],
        bucket_resolver: Optional[BucketKeyResolver] = None,
        seasonality_classifier: Optional[SeasonalityClassifier] = None,
        scorer: Optional[ZScoreScorer] = None,
        poll_timeout_ms: int = 1000,
        guard: Optional[DriftGuard] = None,
    ) -> None:
        self._stream_reader = stream_reader
        self._baseline_store = baseline_store
        self._on_score = on_score
        self._bucket_resolver = bucket_resolver or BucketKeyResolver()
        self._seasonality_classifier = seasonality_classifier or SeasonalityClassifier()
        self._scorer = scorer or ZScoreScorer()
        self._poll_timeout_ms = poll_timeout_ms
        self._running = False
        self._guard = guard
        self._seen_buckets: set = set()

        self.points_processed_total: int = 0
        self.anomalies_flagged_total: int = 0

    def process_point(self, point: MetricPoint) -> ScoreResult:
        """
        The full per-point cycle for ONE MetricPoint. Does not touch the
        stream at all — safe to call directly in tests.
        """
        if self._seasonality_classifier.is_seasonal(point.vm_id, point.metric_name):
            bucket_key = self._bucket_resolver.resolve(
                point.vm_id,
                point.metric_name,
                point.timestamp,
            )
        else:
            bucket_key = BucketKeyResolver.resolve_global(point.vm_id, point.metric_name)

        bucket_state = self._baseline_store.get_bucket_state(bucket_key)
        if bucket_state is None:
            from phase0.types import BucketState
            bucket_state = BucketState()  # brand-new bucket, cold-start

        result = self._scorer.score(
            point.vm_id, point.metric_name, bucket_key, point.value, bucket_state,
        )

        self._seen_buckets.add(bucket_key)

        # Update AFTER scoring — score against the baseline as it stood
        # BEFORE this point, then fold this point in for future points.
        entity = f"{point.vm_id}:{point.metric_name}"
        if self._guard is not None and self._guard.has_snapshot(entity, bucket_key):
            day = point.timestamp.timestamp() / 86400.0
            proposed = self._baseline_store.preview_update(bucket_key, point.value)
            window = list(proposed.window)
            median = statistics.median(window)
            decision = self._guard.evaluate(entity, bucket_key, median, point.value, day)
            result.guard_evaluated = True
            result.guard_d_cumulative = decision.d_cumulative
            result.guard_d_windowed = decision.d_windowed
            if decision.action is GuardAction.HOLD:
                result.guard_held = True
                result.guard_incident = decision.new_incident
                return result
            self._baseline_store.update_bucket(bucket_key, point.value)
            self._guard.record_accepted(entity, bucket_key, median, day)
            return result

        self._baseline_store.update_bucket(bucket_key, point.value)
        return result

    def promote_held(
        self,
        day: float,
        cohort_same_direction_fraction: float,
        operator_approved: bool = False,
        corroborated: Optional[Callable[[str], bool]] = None,
    ) -> int:
        """Try to promote every held entity's shadow baseline. ``day`` is in
        epoch days. Returns the number of entities promoted; entities that do
        not qualify stay held."""
        if self._guard is None:
            return 0
        promoted = 0
        for entity in self._guard.held_entities():
            plan = self._guard.try_promote(
                entity, day, cohort_same_direction_fraction, operator_approved,
                corroborated(entity) if corroborated is not None else None,
            )
            if plan is None:
                continue
            buckets = [k for k in self._seen_buckets if f"{k.vm_id}:{k.metric_name}" == entity]
            for key in buckets:
                if key in plan.bucket_values:
                    values = plan.bucket_values[key]
                else:
                    state = self._baseline_store.get_bucket_state(key)
                    if state is None:
                        continue
                    shift = plan.shift_sigma * plan.scales.get(key, 0.0)
                    values = [v + shift for v in state.window]
                self._baseline_store.reseed_bucket(key, values)
            self._guard.complete_promotion(entity, day, plan.capped)
            self.freeze_snapshots(day, only_entity=entity)
            promoted += 1
        return promoted

    def freeze_snapshots(self, day: float, only_entity: Optional[str] = None) -> int:
        """Take the guard's trusted snapshot of every bucket seen so far
        (optionally for one entity). Returns the number of buckets snapshotted."""
        if self._guard is None:
            return 0
        taken = 0
        for key in list(self._seen_buckets):
            entity = f"{key.vm_id}:{key.metric_name}"
            if only_entity is not None and entity != only_entity:
                continue
            state = self._baseline_store.get_bucket_state(key)
            if state is not None and self._guard.take_snapshot(entity, key, list(state.window), day):
                taken += 1
        return taken

    def process_batch(self, points: List[MetricPoint]) -> List[ScoreResult]:
        """Process a list of points synchronously, publishing each via
        on_score and never letting one bad point stop the batch."""
        results = []
        for point in points:
            try:
                result = self.process_point(point)
                results.append(result)
                self.points_processed_total += 1
                if result.is_anomaly:
                    self.anomalies_flagged_total += 1
                try:
                    self._on_score(result)
                except Exception:
                    logger_obj.exception(
                        "[AnomalyScoringWorker] on_score callback failed — continuing"
                    )
            except Exception:
                logger_obj.exception(
                    "[AnomalyScoringWorker] Failed to process point %r — skipping", point
                )
        return results

    def stop(self) -> None:
        self._running = False
        self._stream_reader.stop()
        logger_obj.info("[AnomalyScoringWorker] Stopped")

    async def run_async(self) -> None:
        self._stream_reader.start()
        self._running = True
        logger_obj.info("[AnomalyScoringWorker] Starting poll loop")

        while self._running:
            try:
                points = self._stream_reader.poll(timeout_ms=self._poll_timeout_ms)
                self.process_batch(points)
            except Exception:
                logger_obj.exception("[AnomalyScoringWorker] poll() cycle failed — continuing")

            await asyncio.sleep(0)
