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
from typing import Callable, List, Optional

from phase0.baseline.rolling_baseline_store import RollingBaselineStore
from phase0.bucketing.bucket_key_resolver import BucketKeyResolver
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
    ) -> None:
        self._stream_reader = stream_reader
        self._baseline_store = baseline_store
        self._on_score = on_score
        self._bucket_resolver = bucket_resolver or BucketKeyResolver()
        self._seasonality_classifier = seasonality_classifier or SeasonalityClassifier()
        self._scorer = scorer or ZScoreScorer()
        self._poll_timeout_ms = poll_timeout_ms
        self._running = False

        self.points_processed_total: int = 0
        self.anomalies_flagged_total: int = 0

    def process_point(self, point: MetricPoint) -> ScoreResult:
        """
        The full per-point cycle for ONE MetricPoint. Does not touch the
        stream at all — safe to call directly in tests.
        """
        if self._seasonality_classifier.is_seasonal(point.vm_id, point.metric_name):
            bucket_key = self._bucket_resolver.resolve(point.vm_id, point.metric_name, point.timestamp)
        else:
            bucket_key = BucketKeyResolver.resolve_global(point.vm_id, point.metric_name)

        bucket_state = self._baseline_store.get_bucket_state(bucket_key)
        if bucket_state is None:
            from phase0.types import BucketState
            bucket_state = BucketState()  # brand-new bucket, cold-start

        result = self._scorer.score(
            point.vm_id, point.metric_name, bucket_key, point.value, bucket_state,
        )

        # Update AFTER scoring — score against the baseline as it stood
        # BEFORE this point, then fold this point in for future points.
        self._baseline_store.update_bucket(bucket_key, point.value)

        return result

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
                    logger_obj.exception("[AnomalyScoringWorker] on_score callback failed — continuing")
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
