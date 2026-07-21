"""
tests/unit/phase0/test_anomaly_scoring_worker.py
=====================================================
Covers: process_point()'s full cycle against a real fakeredis-backed
RollingBaselineStore (not a mock — proven-correct real logic underneath);
cold-start handling for a brand-new bucket; sequential accumulation
eventually flagging a genuine outlier; the global-fallback path via
SeasonalityClassifier; on_score callback invocation and its
crash-isolation; and process_batch continuing after one point fails.
"""
from datetime import datetime, timezone

import fakeredis
import pytest

from phase0.baseline.rolling_baseline_store import RollingBaselineStore
from phase0.scoring.zscore_scorer import ZScoreScorer
from phase0.seasonality.seasonality_classifier import SeasonalityClassifier
from phase0.types import MetricPoint
from phase0.workers.anomaly_scoring_worker import AnomalyScoringWorker


class _StubStreamReader:
    """Minimal BaseStreamReader stand-in — process_point/process_batch
    don't need a real stream, but the constructor requires *something*."""
    def start(self): pass
    def stop(self): pass
    def poll(self, timeout_ms): return []


def _make_worker(**kwargs):
    redis_client = fakeredis.FakeStrictRedis()
    store = RollingBaselineStore(redis_client)
    scored = []
    worker = AnomalyScoringWorker(
        stream_reader=_StubStreamReader(),
        baseline_store=store,
        on_score=lambda r: scored.append(r),
        scorer=ZScoreScorer(min_samples=kwargs.get("min_samples", 1)),
        **{k: v for k, v in kwargs.items() if k != "min_samples"},
    )
    return worker, scored


def _point(vm_id="vm-042", metric="cpu_usage", value=60.0, hour=3):
    return MetricPoint(
        vm_id=vm_id, metric_name=metric,
        timestamp=datetime(2025, 11, 11, hour, 0, tzinfo=timezone.utc),
        value=value,
    )


class TestColdStart:
    def test_brand_new_bucket_is_cold_start_not_anomalous(self):
        worker, scored = _make_worker(min_samples=5)
        result = worker.process_point(_point())
        assert result.cold_start is True
        assert result.is_anomaly is False

    def test_bucket_is_updated_after_scoring(self):
        worker, scored = _make_worker()
        worker.process_point(_point(value=60.0))
        state = worker._baseline_store.get_bucket_state(
            worker._bucket_resolver.resolve("vm-042", "cpu_usage", _point().timestamp)
        )
        assert state.count == 1
        assert state.mean == pytest.approx(60.0)


class TestSequentialAccumulationAndAnomalyDetection:
    def test_stable_readings_then_a_genuine_outlier_gets_flagged(self):
        worker, scored = _make_worker(min_samples=5)
        # Feed 10 stable readings around 62 +/- 1
        for v in [61, 62, 63, 62, 61, 62, 63, 61, 62, 63]:
            worker.process_point(_point(value=float(v)))

        # Now an extreme outlier at the same bucket
        result = worker.process_point(_point(value=200.0))
        assert result.is_anomaly is True
        assert result.z_score > 3.0

    def test_scored_callback_receives_every_result(self):
        worker, scored = _make_worker()
        points = [_point(value=float(v)) for v in [60, 61, 62]]
        worker.process_batch(points)
        assert len(scored) == 3


class TestGlobalFallback:
    def test_non_seasonal_metric_uses_global_bucket_regardless_of_hour(self):
        worker, scored = _make_worker(
            seasonality_classifier=SeasonalityClassifier(non_seasonal_metrics=["disk_capacity"])
        )
        p1 = _point(metric="disk_capacity", value=500.0, hour=3)
        p2 = _point(metric="disk_capacity", value=505.0, hour=18)  # different hour
        worker.process_point(p1)
        result2 = worker.process_point(p2)

        # Both points should have landed in the SAME (global) bucket,
        # despite different hours -> count should be 2 by the second point
        assert result2.bucket_key.is_global()


class TestBatchProcessingResilience:
    def test_process_batch_continues_after_on_score_raises(self):
        redis_client = fakeredis.FakeStrictRedis()
        store = RollingBaselineStore(redis_client)

        def bad_callback(result):
            if result.value == 999.0:
                raise RuntimeError("simulated callback failure")

        worker = AnomalyScoringWorker(
            stream_reader=_StubStreamReader(),
            baseline_store=store,
            on_score=bad_callback,
        )

        points = [_point(value=60.0), _point(value=999.0), _point(value=61.0)]
        results = worker.process_batch(points)

        # All 3 points should still have been processed and returned,
        # even though the callback blew up on the middle one.
        assert len(results) == 3
        assert worker.points_processed_total == 3

    def test_health_counters_track_anomalies(self):
        worker, scored = _make_worker(min_samples=5)
        points = [_point(value=float(v)) for v in [61, 62, 63, 62, 61, 62]]
        points.append(_point(value=500.0))  # one clear anomaly
        worker.process_batch(points)

        assert worker.points_processed_total == 7
        assert worker.anomalies_flagged_total == 1
