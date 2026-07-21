"""
phase2/store/entity_store_writer.py
=====================================================
P2-M6  Dynamic Entity Store — EntityStoreWriter
CAPSTONE-189

Concrete, Redis-backed implementation of BaseEntityStoreWriter. This is
the ONLY store dependency ReferenceEncoderService (P2-M4) should ever
import (ISP — see base_entity_store.py docstring).

History rotation
-----------------
history_key(entity_id) is a Redis LIST, newest-first. A single new
window-embedding is added via LPUSH (push onto the head) immediately
followed by LTRIM 0 (history_len_int - 1) in the SAME pipeline
(MULTI/EXEC), so a reader can never observe the list mid-rotation (e.g.
31 entries before the trim lands). A full profile rewrite
(write_entity_profile) replaces the whole list: DELETE, then LPUSH each
embedding in the profile's oldest-first order (which, because LPUSH
always inserts at the head, naturally reassembles as newest-first in
Redis), then one LTRIM as a safety net. Both paths go through the same
`_push_and_trim` pipeline helper so there is exactly one place that
implements the atomic rotation contract.

Why this class also reads (fetch_entity_profile)
----------------------------------------------------
See base_entity_store.py's module docstring
("Why BaseEntityStoreWriter also declares fetch_entity_profile").
ReferenceEncoderService's incremental EMA update needs the PRIOR
centroid/variance/history before it can blend in a new observation, and
it is only ever given a Writer (not a Reader). Internally this class
delegates that read to a private EntityStoreReader over the same Redis
connection rather than re-implementing the read/deserialize logic a
second time (DRY) -- it does NOT expose that reader externally, so a
caller holding only an EntityStoreWriter still cannot browse OTHER
entities' profiles through some back door; it can only read the one
profile it is about to overwrite.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from redis import Redis

from phase2.store.base_entity_store import (
    BaseEntityStoreWriter,
    centroid_key,
    current_key,
    history_key,
    serialize_emb_f16,
    stats_key,
)
from phase2.store.entity_store_reader import EntityStoreReader
from shared.constants import REDIS_HISTORY_LEN
from shared.types import CurrentEmbedding, EntityProfile

logger_obj: logging.Logger = logging.getLogger(__name__)


class EntityStoreWriter(BaseEntityStoreWriter):
    """
    Parameters
    ----------
    redis_client_sync:
        A connected `redis.Redis` instance (decode_responses=False --
        see EntityStoreReader's identical constraint).
    history_len_int:
        Max history_embeddings entries kept per entity (LTRIM cap).
    """

    def __init__(
        self,
        redis_client_sync: Redis,
        history_len_int: int = REDIS_HISTORY_LEN,
    ) -> None:
        self._redis = redis_client_sync
        self._history_len_int = history_len_int
        # Internal-only read path for the EMA "read prior profile" need --
        # never exposed as a public attribute (see module docstring).
        self._internal_reader = EntityStoreReader(
            redis_client_sync=redis_client_sync, history_len_int=history_len_int,
        )

    # ── Reads needed by the write path ──────────────────────────────────────

    def fetch_entity_profile(self, entity_id: str) -> Optional[EntityProfile]:
        return self._internal_reader.fetch_entity_profile(entity_id)

    # ── Writes ───────────────────────────────────────────────────────────────

    def write_current_embedding(self, current_embedding: CurrentEmbedding) -> None:
        self._redis.set(
            current_key(current_embedding.entity_id),
            serialize_emb_f16(current_embedding.emb),
        )

    def write_entity_profile(self, profile: EntityProfile) -> None:
        """
        Atomically (single MULTI/EXEC pipeline) overwrite centroid_ema,
        the full history_embeddings list, and the stats hash for
        profile.entity_id. Used by ReferenceEncoderService's full
        (re)build path AND its incremental EMA path (both call this once
        they have the final EntityProfile to persist).
        """
        entity_id = profile.entity_id
        with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(centroid_key(entity_id), serialize_emb_f16(profile.centroid_emb))

            pipe.delete(history_key(entity_id))
            for emb in profile.history_embs:  # oldest-first in; LPUSH reassembles newest-first
                pipe.lpush(history_key(entity_id), serialize_emb_f16(emb))
            pipe.ltrim(history_key(entity_id), 0, self._history_len_int - 1)

            pipe.hset(
                stats_key(entity_id),
                mapping={
                    "last_update_ts": profile.last_update_ts.isoformat(),
                    "record_count": str(profile.n_records),
                    "embedding_variance": repr(profile.emb_variance),
                    "cold_start_flag": "1" if profile.cold_start_flag else "0",
                },
            )
            pipe.execute()

        logger_obj.debug(
            "[EntityStoreWriter] wrote profile entity_id=%s n_history=%d "
            "record_count=%d cold_start=%s",
            entity_id, len(profile.history_embs), profile.n_records, profile.cold_start_flag,
        )

    def append_history_embedding(self, entity_id: str, new_emb: np.ndarray) -> None:
        """
        Atomic single-entry rotation: LPUSH the new embedding, LTRIM to
        history_len_int, in one pipeline. Does NOT touch centroid_ema or
        stats -- callers that need those updated too should go through
        write_entity_profile() instead; this method is for call sites
        that only have one new embedding and want the cheapest possible
        append (e.g. a lightweight streaming path that recomputes
        centroid/variance elsewhere).
        """
        with self._redis.pipeline(transaction=True) as pipe:
            pipe.lpush(history_key(entity_id), serialize_emb_f16(new_emb))
            pipe.ltrim(history_key(entity_id), 0, self._history_len_int - 1)
            pipe.execute()