"""
phase2/store/entity_store_reader.py
=====================================================
P2-M6  Dynamic Entity Store — EntityStoreReader
CAPSTONE-189

Concrete, Redis-backed implementation of BaseEntityStoreReader. This is
the ONLY store dependency P2-M7 (CosineDeviationScorer), P2-M8
(MmdDriftMonitor), and P2-M9 (EpisodeRetriever) should ever import (ISP:
"Interface Segregation" — see base_entity_store.py docstring).

Sync + async
------------
Every read has both a sync method (redis-py's standard blocking client,
`redis.Redis`) and an async method (redis-py's built-in asyncio client,
`redis.asyncio.Redis` — this project's stand-in for what the planner
calls "aioredis"; aioredis itself is unmaintained and its functionality
was merged into redis-py >= 4.2). The async path is for the
high-throughput inference loop (P2-M3/P2-M7/P2-M8/P2-M9 batch scoring);
the sync path is for CLI scripts, notebooks, and tests.

Both clients point at the SAME Redis keys — they are just two transport
options over the identical wire format defined in base_entity_store.py.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from phase2.store.base_entity_store import (
    BaseEntityStoreReader,
    STATS_KEY_GLOB,
    centroid_key,
    current_key,
    deserialize_emb_f16,
    entity_id_from_stats_key,
    history_key,
    stats_key,
)
from shared.constants import REDIS_HISTORY_LEN
from shared.types import EntityProfile

logger_obj: logging.Logger = logging.getLogger(__name__)


class EntityStoreReader(BaseEntityStoreReader):
    """
    Parameters
    ----------
    redis_client_sync:
        A connected `redis.Redis` instance (decode_responses=False --
        this class handles bytes itself; do NOT pass a client configured
        with decode_responses=True or embedding bytes will be corrupted
        by UTF-8 decoding attempts).
    redis_client_async:
        A connected `redis.asyncio.Redis` instance, same decode_responses
        constraint. Optional -- only required if the async methods are
        actually called; a client that only ever uses the sync methods
        (e.g. a notebook) can omit this.
    history_len_int:
        Cap on how many history embeddings a single profile can hold --
        used only to sanity-check what comes back from Redis, never to
        truncate; truncation is EntityStoreWriter's job at write time.
    """

    def __init__(
        self,
        redis_client_sync: Redis,
        redis_client_async: Optional[AsyncRedis] = None,
        history_len_int: int = REDIS_HISTORY_LEN,
    ) -> None:
        self._redis = redis_client_sync
        self._redis_async = redis_client_async
        self._history_len_int = history_len_int

    # ── Sync reads ───────────────────────────────────────────────────────────

    def fetch_current_embedding(self, entity_id: str) -> Optional[np.ndarray]:
        raw_bytes = self._redis.get(current_key(entity_id))
        if raw_bytes is None:
            return None
        return deserialize_emb_f16(raw_bytes)

    def fetch_entity_profile(self, entity_id: str) -> Optional[EntityProfile]:
        with self._redis.pipeline(transaction=True) as pipe:
            pipe.get(centroid_key(entity_id))
            pipe.lrange(history_key(entity_id), 0, -1)
            pipe.hgetall(stats_key(entity_id))
            centroid_raw, history_raw_list, stats_raw_dict = pipe.execute()
        return self._assemble_profile(entity_id, centroid_raw, history_raw_list, stats_raw_dict)

    def list_known_entity_ids(self) -> List[str]:
        entity_ids: List[str] = []
        for key_bytes in self._redis.scan_iter(match=STATS_KEY_GLOB, count=500):
            key_str = key_bytes.decode("utf-8") if isinstance(key_bytes, bytes) else key_bytes
            entity_ids.append(entity_id_from_stats_key(key_str))
        return entity_ids

    # ── Async reads (high-throughput inference path) ───────────────────────

    async def fetch_current_embedding_async(self, entity_id: str) -> Optional[np.ndarray]:
        if self._redis_async is None:
            raise RuntimeError(
                "[EntityStoreReader] redis_client_async was not provided at construction "
                "-- pass one to use the async read path."
            )
        raw_bytes = await self._redis_async.get(current_key(entity_id))
        if raw_bytes is None:
            return None
        return deserialize_emb_f16(raw_bytes)

    async def fetch_entity_profile_async(self, entity_id: str) -> Optional[EntityProfile]:
        if self._redis_async is None:
            raise RuntimeError(
                "[EntityStoreReader] redis_client_async was not provided at construction "
                "-- pass one to use the async read path."
            )
        async with self._redis_async.pipeline(transaction=True) as pipe:
            pipe.get(centroid_key(entity_id))
            pipe.lrange(history_key(entity_id), 0, -1)
            pipe.hgetall(stats_key(entity_id))
            centroid_raw, history_raw_list, stats_raw_dict = await pipe.execute()
        return self._assemble_profile(entity_id, centroid_raw, history_raw_list, stats_raw_dict)

    # ── Shared assembly logic (sync + async paths both funnel through this) ─

    def _assemble_profile(
        self,
        entity_id: str,
        centroid_raw: Optional[bytes],
        history_raw_list: List[bytes],
        stats_raw_dict: dict,
    ) -> Optional[EntityProfile]:
        """
        Turn raw Redis reply pieces into an EntityProfile, or None if the
        entity has no profile at all (missing centroid AND empty stats).
        """
        if centroid_raw is None and not stats_raw_dict and not history_raw_list:
            return None

        centroid_emb = (
            deserialize_emb_f16(centroid_raw) if centroid_raw is not None
            else np.zeros(128, dtype=np.float32)
        )

        # history is stored newest-first (LPUSH+LTRIM, see EntityStoreWriter);
        # EntityProfile's contract is chronological oldest-first -- reverse it.
        history_embs = [deserialize_emb_f16(raw) for raw in reversed(history_raw_list)]
        if len(history_embs) > self._history_len_int:
            logger_obj.warning(
                "[EntityStoreReader] entity_id=%s history longer than expected "
                "(%d > %d) -- LTRIM cap may not be enforced by the writer that "
                "produced it.",
                entity_id, len(history_embs), self._history_len_int,
            )

        def _stat(field_name: str, default: str) -> bytes:
            return stats_raw_dict.get(field_name.encode("utf-8"), default.encode("utf-8"))

        last_update_ts_str = _stat("last_update_ts", "1970-01-01T00:00:00+00:00").decode("utf-8")
        record_count_int = int(_stat("record_count", "0"))
        embedding_variance_float = float(_stat("embedding_variance", "0.0"))
        cold_start_flag_bool = _stat("cold_start_flag", "0") == b"1"

        from datetime import datetime  # local import: keep module-level imports lean

        return EntityProfile(
            entity_id=entity_id,
            centroid_emb=centroid_emb,
            history_embs=history_embs,
            emb_variance=embedding_variance_float,
            n_records=record_count_int,
            last_update_ts=datetime.fromisoformat(last_update_ts_str),
            cold_start_flag=cold_start_flag_bool,
        )