"""
tests/unit/phase2/test_entity_store.py
Smoke tests for P2-M6 against fakeredis (in-memory, no real Redis needed).
"""
import asyncio
from datetime import datetime, timezone

import numpy as np
import fakeredis

from phase2.store.entity_store_reader import EntityStoreReader
from phase2.store.entity_store_writer import EntityStoreWriter
from phase2.store.redis_entity_store import RedisEntityStore, DynamicEntityStore
from shared.types import CurrentEmbedding, EntityProfile


def rand_unit_emb(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


def test_write_and_read_profile_roundtrip():
    r = fakeredis.FakeRedis(decode_responses=False)
    writer = EntityStoreWriter(redis_client_sync=r)
    reader = EntityStoreReader(redis_client_sync=r)

    history = [rand_unit_emb(i) for i in range(5)]  # oldest-first
    profile = EntityProfile(
        entity_id="vm-001",
        centroid_emb=rand_unit_emb(99),
        history_embs=history,
        emb_variance=0.1234,
        n_records=5,
        last_update_ts=datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc),
        cold_start_flag=False,
    )
    writer.write_entity_profile(profile)

    fetched = reader.fetch_entity_profile("vm-001")
    assert fetched is not None
    assert fetched.entity_id == "vm-001"
    np.testing.assert_allclose(fetched.centroid_emb, profile.centroid_emb, atol=1e-3)
    assert fetched.n_records == 5
    assert fetched.cold_start_flag is False
    assert abs(fetched.emb_variance - 0.1234) < 1e-6
    assert len(fetched.history_embs) == 5
    # chronological oldest-first must round-trip in the SAME order it went in
    for original, restored in zip(history, fetched.history_embs):
        np.testing.assert_allclose(original, restored, atol=1e-3)
    print("test_write_and_read_profile_roundtrip PASSED")


def test_missing_entity_returns_none():
    r = fakeredis.FakeRedis(decode_responses=False)
    reader = EntityStoreReader(redis_client_sync=r)
    assert reader.fetch_entity_profile("does-not-exist") is None
    assert reader.fetch_current_embedding("does-not-exist") is None
    print("test_missing_entity_returns_none PASSED")


def test_current_embedding_write_read():
    r = fakeredis.FakeRedis(decode_responses=False)
    writer = EntityStoreWriter(redis_client_sync=r)
    reader = EntityStoreReader(redis_client_sync=r)
    emb = rand_unit_emb(7)
    ce = CurrentEmbedding(
        entity_id="vm-002", emb=emb,
        batch_ts=datetime.now(timezone.utc), n_records=3, cloud_provider="AWS",
    )
    writer.write_current_embedding(ce)
    fetched_emb = reader.fetch_current_embedding("vm-002")
    assert fetched_emb is not None
    np.testing.assert_allclose(fetched_emb, emb, atol=1e-3)
    print("test_current_embedding_write_read PASSED")


def test_history_rotation_caps_at_30_and_is_newest_first_internally():
    r = fakeredis.FakeRedis(decode_responses=False)
    writer = EntityStoreWriter(redis_client_sync=r, history_len_int=30)
    reader = EntityStoreReader(redis_client_sync=r, history_len_int=30)

    # Append 35 individual embeddings incrementally (oldest to newest)
    embs = [rand_unit_emb(i) for i in range(35)]
    for e in embs:
        writer.append_history_embedding("vm-003", e)

    raw_list = r.lrange(b"entity:vm-003:history", 0, -1)
    assert len(raw_list) == 30, f"expected cap of 30, got {len(raw_list)}"

    # Reconstruct via reader path: should equal the LAST 30 embeddings pushed,
    # oldest-first (i.e. embs[5:35])
    profile_stub = reader._assemble_profile(
        "vm-003",
        centroid_raw=None,
        history_raw_list=raw_list,
        stats_raw_dict={},
    )
    assert profile_stub is not None
    assert len(profile_stub.history_embs) == 30
    expected_tail = embs[5:]  # last 30, oldest-first
    for expected, actual in zip(expected_tail, profile_stub.history_embs):
        np.testing.assert_allclose(expected, actual, atol=1e-3)
    print("test_history_rotation_caps_at_30_and_is_newest_first_internally PASSED")


def test_list_known_entity_ids():
    r = fakeredis.FakeRedis(decode_responses=False)
    writer = EntityStoreWriter(redis_client_sync=r)
    reader = EntityStoreReader(redis_client_sync=r)
    for i in range(3):
        profile = EntityProfile(
            entity_id=f"vm-{i}",
            centroid_emb=rand_unit_emb(i),
            history_embs=[rand_unit_emb(i)],
            emb_variance=0.0,
            n_records=1,
            last_update_ts=datetime.now(timezone.utc),
        )
        writer.write_entity_profile(profile)
    ids = set(reader.list_known_entity_ids())
    assert ids == {"vm-0", "vm-1", "vm-2"}
    print("test_list_known_entity_ids PASSED")


def test_writer_fetch_entity_profile_for_ema_read_before_write():
    """Mirrors ReferenceEncoderService.update_profile_incremental()'s usage:
    entity_store_writer.fetch_entity_profile(entity_id) must work even
    though the caller was only ever given a Writer."""
    r = fakeredis.FakeRedis(decode_responses=False)
    writer = EntityStoreWriter(redis_client_sync=r)
    profile = EntityProfile(
        entity_id="vm-ema",
        centroid_emb=rand_unit_emb(1),
        history_embs=[rand_unit_emb(1)],
        emb_variance=0.05,
        n_records=1,
        last_update_ts=datetime.now(timezone.utc),
    )
    writer.write_entity_profile(profile)
    prior = writer.fetch_entity_profile("vm-ema")  # <-- the exact call P2-M4 makes
    assert prior is not None
    assert prior.entity_id == "vm-ema"
    print("test_writer_fetch_entity_profile_for_ema_read_before_write PASSED")


def test_redis_entity_store_facade_delegates_both_sides():
    r = fakeredis.FakeRedis(decode_responses=False)
    assert DynamicEntityStore is RedisEntityStore  # alias sanity
    store = RedisEntityStore(redis_client_sync=r)
    profile = EntityProfile(
        entity_id="vm-facade",
        centroid_emb=rand_unit_emb(2),
        history_embs=[rand_unit_emb(2)],
        emb_variance=0.02,
        n_records=1,
        last_update_ts=datetime.now(timezone.utc),
    )
    store.write_entity_profile(profile)
    fetched = store.fetch_entity_profile("vm-facade")
    assert fetched is not None and fetched.entity_id == "vm-facade"
    print("test_redis_entity_store_facade_delegates_both_sides PASSED")


def test_async_reads():
    async def _run():
        import fakeredis.aioredis as fakeredis_aio

        shared_server = fakeredis.FakeServer()
        sync_client = fakeredis.FakeRedis(server=shared_server, decode_responses=False)
        async_client = fakeredis_aio.FakeRedis(server=shared_server, decode_responses=False)

        writer = EntityStoreWriter(redis_client_sync=sync_client)
        reader = EntityStoreReader(redis_client_sync=sync_client, redis_client_async=async_client)

        profile = EntityProfile(
            entity_id="vm-async",
            centroid_emb=rand_unit_emb(3),
            history_embs=[rand_unit_emb(3)],
            emb_variance=0.03,
            n_records=1,
            last_update_ts=datetime.now(timezone.utc),
        )
        writer.write_entity_profile(profile)

        fetched = await reader.fetch_entity_profile_async("vm-async")
        assert fetched is not None
        assert fetched.entity_id == "vm-async"

        current_emb = rand_unit_emb(4)
        writer.write_current_embedding(
            CurrentEmbedding(entity_id="vm-async2", emb=current_emb,
                              batch_ts=datetime.now(timezone.utc), n_records=1, cloud_provider="OCI")
        )
        fetched_cur = await reader.fetch_current_embedding_async("vm-async2")
        assert fetched_cur is not None
        np.testing.assert_allclose(fetched_cur, current_emb, atol=1e-3)
        print("test_async_reads PASSED")

    asyncio.run(_run())


if __name__ == "__main__":
    test_write_and_read_profile_roundtrip()
    test_missing_entity_returns_none()
    test_current_embedding_write_read()
    test_history_rotation_caps_at_30_and_is_newest_first_internally()
    test_list_known_entity_ids()
    test_writer_fetch_entity_profile_for_ema_read_before_write()
    test_redis_entity_store_facade_delegates_both_sides()
    try:
        test_async_reads()
    except Exception as e:
        print("test_async_reads FAILED (will fix):", repr(e))
        raise