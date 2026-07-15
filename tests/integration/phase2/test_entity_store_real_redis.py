"""
tests/integration/phase2/test_entity_store_real_redis.py
Run this ONLY after a real Redis is reachable at localhost:6379
(e.g. `docker run -d --name capstone-redis -p 6379:6379 redis:7-alpine`).

This is NOT the fakeredis smoke test (tests/unit/phase2/test_entity_store.py) --
it makes real network calls to real Redis, to confirm nothing about real
Redis's pipeline/LTRIM/SCAN behavior differs from fakeredis's simulation.

Run with:
    python -m tests.integration.phase2.test_entity_store_real_redis
"""
from datetime import datetime, timezone

import numpy as np

from phase2.store.redis_entity_store import build_redis_client, RedisEntityStore
from shared.types import CurrentEmbedding, EntityProfile


def rand_unit_emb(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


def main() -> None:
    r = build_redis_client(host_str="localhost", port_int=6379)

    # Fail fast with a clear message if Redis isn't reachable, instead of a
    # confusing connection-refused traceback deep inside redis-py.
    try:
        r.ping()
    except Exception as exc:
        raise RuntimeError(
            "Could not reach Redis at localhost:6379 -- is the container "
            "running? (`docker ps` should show capstone-redis)"
        ) from exc
    print("Connected to real Redis at localhost:6379")

    store = RedisEntityStore(redis_client_sync=r)

    # Clean slate for this test entity so re-runs are deterministic
    entity_id = "integration-test-vm"
    r.delete(f"entity:{entity_id}:current", f"entity:{entity_id}:centroid",
              f"entity:{entity_id}:history", f"entity:{entity_id}:stats")

    profile = EntityProfile(
        entity_id=entity_id,
        centroid_emb=rand_unit_emb(1),
        history_embs=[rand_unit_emb(i) for i in range(5)],
        emb_variance=0.42,
        n_records=5,
        last_update_ts=datetime.now(timezone.utc),
        cold_start_flag=False,
    )
    store.write_entity_profile(profile)
    print(f"Wrote profile for entity_id={entity_id}")

    fetched = store.fetch_entity_profile(entity_id)
    assert fetched is not None
    assert fetched.entity_id == entity_id
    assert fetched.n_records == 5
    assert len(fetched.history_embs) == 5
    np.testing.assert_allclose(fetched.centroid_emb, profile.centroid_emb, atol=1e-3)
    print("Round-trip read matched what was written -- PASSED")

    current_emb = rand_unit_emb(99)
    store.write_current_embedding(
        CurrentEmbedding(entity_id=entity_id, emb=current_emb,
                          batch_ts=datetime.now(timezone.utc), n_records=1, cloud_provider="AWS")
    )
    fetched_current = store.fetch_current_embedding(entity_id)
    assert fetched_current is not None
    np.testing.assert_allclose(fetched_current, current_emb, atol=1e-3)
    print("current_embedding round-trip PASSED")

    ids = store.list_known_entity_ids()
    assert entity_id in ids
    print(f"list_known_entity_ids() found {len(ids)} entities, including our test entity -- PASSED")

    # Cleanup
    r.delete(f"entity:{entity_id}:current", f"entity:{entity_id}:centroid",
              f"entity:{entity_id}:history", f"entity:{entity_id}:stats")
    print("\nAll real-Redis integration checks PASSED.")


if __name__ == "__main__":
    main()