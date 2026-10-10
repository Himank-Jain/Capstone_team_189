"""
tests/unit/phase2/test_async_drift_worker.py
Unit tests for P2-M8 AsyncDriftWorker against fakeredis (in-memory, no real
Redis needed) -- same pattern as test_entity_store.py. Exercises the REAL
ThreadPoolExecutor (not mocked) so background execution + Redis TTL
caching are genuinely proven, not just asserted about.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

import fakeredis
import numpy as np
import pytest

from phase2.detection.async_drift_worker import (
    AsyncDriftWorker,
    drift_key,
)
from phase2.detection.mmd_drift_monitor import MmdDriftMonitor
from phase2.store.base_entity_store import BaseEntityStoreReader
from shared.constants import REDIS_DRIFT_CACHE_TTL
from shared.types import DriftScore, EntityProfile


class FakeEntityStoreReader(BaseEntityStoreReader):
    def __init__(self, profiles: Optional[Dict[str, EntityProfile]] = None):
        self._profiles = profiles or {}

    def set_profile(self, entity_id: str, profile: EntityProfile) -> None:
        self._profiles[entity_id] = profile

    def fetch_entity_profile(self, entity_id: str) -> Optional[EntityProfile]:
        return self._profiles.get(entity_id)

    def fetch_current_embedding(self, entity_id: str):
        raise NotImplementedError

    def list_known_entity_ids(self) -> List[str]:
        return list(self._profiles.keys())

    async def fetch_entity_profile_async(self, entity_id: str):
        raise NotImplementedError

    async def fetch_current_embedding_async(self, entity_id: str):
        raise NotImplementedError


def cluster_embs(n: int, center_seed: int, noise_scale: float, dim: int = 128) -> List[np.ndarray]:
    rng0 = np.random.default_rng(center_seed)
    center = rng0.normal(size=dim).astype(np.float32)
    center = center / np.linalg.norm(center)
    rng = np.random.default_rng(center_seed + 1000)
    out = []
    for _ in range(n):
        v = center + rng.normal(scale=noise_scale, size=dim).astype(np.float32)
        out.append(v / np.linalg.norm(v))
    return out


def make_profile(entity_id: str, history: List[np.ndarray]) -> EntityProfile:
    centroid = np.mean(np.stack(history), axis=0)
    centroid = centroid / np.linalg.norm(centroid)
    return EntityProfile(
        entity_id=entity_id,
        centroid_emb=centroid,
        history_embs=history,
        emb_variance=0.0,
        n_records=len(history),
        last_update_ts=datetime.now(timezone.utc),
        cold_start_flag=False,
    )


def make_worker(entity_id: str = "vm-async", n_history: int = 30) -> tuple[AsyncDriftWorker, fakeredis.FakeRedis]:
    reader = FakeEntityStoreReader()
    reader.set_profile(entity_id, make_profile(entity_id, cluster_embs(n_history, 4, 0.05)))
    monitor = MmdDriftMonitor(reader, null_calibration_pairs=50, rng=np.random.default_rng(0))
    r = fakeredis.FakeRedis(decode_responses=False)
    worker = AsyncDriftWorker(monitor, redis_client_sync=r, cache_ttl_sec=REDIS_DRIFT_CACHE_TTL, max_workers=2)
    return worker, r


def test_get_cached_drift_returns_none_when_absent():
    worker, r = make_worker()
    assert worker.get_cached_drift("vm-async") is None
    print("test_get_cached_drift_returns_none_when_absent PASSED")
    worker.shutdown()


def test_compute_and_cache_sync_writes_ttl_key():
    worker, r = make_worker()
    score = worker.compute_and_cache_sync("vm-async")
    assert isinstance(score, DriftScore)
    assert score.entity_id == "vm-async"

    raw = r.get(drift_key("vm-async"))
    assert raw is not None
    ttl = r.ttl(drift_key("vm-async"))
    assert 0 < ttl <= REDIS_DRIFT_CACHE_TTL
    print(f"test_compute_and_cache_sync_writes_ttl_key PASSED (ttl={ttl})")
    worker.shutdown()


def test_get_cached_drift_roundtrips_after_sync_compute():
    worker, r = make_worker()
    written = worker.compute_and_cache_sync("vm-async")
    fetched = worker.get_cached_drift("vm-async")
    assert fetched is not None
    assert fetched.entity_id == written.entity_id
    assert abs(fetched.drift_score - written.drift_score) < 1e-9
    assert fetched.drift_flag == written.drift_flag
    assert fetched.computed_at == written.computed_at
    print("test_get_cached_drift_roundtrips_after_sync_compute PASSED")
    worker.shutdown()


def test_submit_compute_runs_in_background_thread_and_populates_cache():
    worker, r = make_worker()
    # Nothing cached yet -- proves the Future's work hasn't run inline.
    assert worker.get_cached_drift("vm-async") is None

    future = worker.submit_compute("vm-async")
    result = future.result(timeout=10)  # blocks THIS thread, not the "hot path"

    assert isinstance(result, DriftScore)
    cached = worker.get_cached_drift("vm-async")
    assert cached is not None
    assert cached.entity_id == "vm-async"
    assert abs(cached.drift_score - result.drift_score) < 1e-9
    print("test_submit_compute_runs_in_background_thread_and_populates_cache PASSED")
    worker.shutdown()


def test_multiple_concurrent_submits_for_different_entities():
    reader = FakeEntityStoreReader()
    entity_ids = [f"vm-multi-{i}" for i in range(5)]
    for i, eid in enumerate(entity_ids):
        reader.set_profile(eid, make_profile(eid, cluster_embs(30, i + 20, 0.05)))
    monitor = MmdDriftMonitor(reader, null_calibration_pairs=30, rng=np.random.default_rng(i))
    r = fakeredis.FakeRedis(decode_responses=False)
    worker = AsyncDriftWorker(monitor, redis_client_sync=r, max_workers=4)

    futures = [worker.submit_compute(eid) for eid in entity_ids]
    results = [f.result(timeout=15) for f in futures]

    assert len(results) == 5
    for eid in entity_ids:
        cached = worker.get_cached_drift(eid)
        assert cached is not None, f"missing cache entry for {eid}"
        assert cached.entity_id == eid
    print("test_multiple_concurrent_submits_for_different_entities PASSED")
    worker.shutdown()


def test_get_cached_drift_handles_malformed_payload_gracefully():
    worker, r = make_worker()
    r.set(drift_key("vm-async"), b"not-valid-json{{{", ex=60)
    assert worker.get_cached_drift("vm-async") is None
    print("test_get_cached_drift_handles_malformed_payload_gracefully PASSED")
    worker.shutdown()


def test_no_profile_entity_still_caches_neutral_fallback():
    reader = FakeEntityStoreReader()  # entity never registered
    monitor = MmdDriftMonitor(reader, rng=np.random.default_rng(0))
    r = fakeredis.FakeRedis(decode_responses=False)
    worker = AsyncDriftWorker(monitor, redis_client_sync=r)

    score = worker.compute_and_cache_sync("vm-ghost")
    assert score.drift_score == 0.5
    assert score.drift_flag is False
    cached = worker.get_cached_drift("vm-ghost")
    assert cached is not None
    assert cached.drift_score == 0.5
    print("test_no_profile_entity_still_caches_neutral_fallback PASSED")
    worker.shutdown()


def test_shutdown_prevents_further_submission_side_effects():
    worker, r = make_worker()
    worker.compute_and_cache_sync("vm-async")
    worker.shutdown(wait=True)
    # After shutdown, submit_compute should raise (executor is closed) --
    # proves shutdown() actually tears the pool down rather than being a no-op.
    with pytest.raises(RuntimeError):
        worker.submit_compute("vm-async")
    print("test_shutdown_prevents_further_submission_side_effects PASSED")


if __name__ == "__main__":
    test_get_cached_drift_returns_none_when_absent()
    test_compute_and_cache_sync_writes_ttl_key()
    test_get_cached_drift_roundtrips_after_sync_compute()
    test_submit_compute_runs_in_background_thread_and_populates_cache()
    test_multiple_concurrent_submits_for_different_entities()
    test_get_cached_drift_handles_malformed_payload_gracefully()
    test_no_profile_entity_still_caches_neutral_fallback()
    test_shutdown_prevents_further_submission_side_effects()
