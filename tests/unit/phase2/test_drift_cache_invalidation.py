import fakeredis

from phase2.detection.async_drift_worker import AsyncDriftWorker, drift_key


def test_drift_worker_can_invalidate_cached_score():
    redis = fakeredis.FakeStrictRedis(decode_responses=False)
    worker = AsyncDriftWorker(None, redis, max_workers=1)
    try:
        redis.set(drift_key("entity-a"), b"cached")
        worker.invalidate_cached_drift("entity-a")
        assert redis.get(drift_key("entity-a")) is None
    finally:
        worker.shutdown()
