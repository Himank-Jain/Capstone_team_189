"""
Throwaway script -- writes one profile to Redis and leaves it there
(no cleanup) so you can poke at it with redis-cli afterwards.

Run:
    python -m scripts.write_and_leave_for_inspection
Then in another terminal:
    docker exec -it capstone-redis redis-cli
    > KEYS entity:*
    > LRANGE entity:inspect-me:history 0 -1
"""
from datetime import datetime, timezone

import numpy as np

from phase2.store.redis_entity_store import build_redis_client, RedisEntityStore
from shared.types import EntityProfile


def rand_unit_emb(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


def main() -> None:
    r = build_redis_client(host_str="localhost", port_int=6379)
    r.ping()
    store = RedisEntityStore(redis_client_sync=r)

    profile = EntityProfile(
        entity_id="inspect-me",
        centroid_emb=rand_unit_emb(1),
        history_embs=[rand_unit_emb(i) for i in range(5)],
        emb_variance=0.42,
        n_records=5,
        last_update_ts=datetime.now(timezone.utc),
        cold_start_flag=False,
    )
    store.write_entity_profile(profile)
    print("Wrote entity_id='inspect-me' to Redis -- NOT cleaned up. Go look with redis-cli.")


if __name__ == "__main__":
    main()