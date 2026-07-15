"""
phase2/store/redis_entity_store.py
=====================================================
P2-M6  Dynamic Entity Store — RedisEntityStore
CAPSTONE-189

[P2-M6 EntityStore]  (primer, Project Directory Structure §6b)
Redis primary. ... RedisEntityStore: implements the same
EntityStoreReader / EntityStoreWriter interfaces [as PgVectorEntityStore].
Async methods via aioredis.

What this class is
--------------------
A thin composition of EntityStoreReader + EntityStoreWriter sharing one
underlying Redis connection (pool), for callers that legitimately need
BOTH sides (e.g. an ops CLI, a test harness, or a startup script that
seeds profiles and then immediately reads them back). It implements
BOTH BaseEntityStoreReader and BaseEntityStoreWriter by delegating every
method to whichever of the two internal objects owns it -- it does not
reimplement any Redis logic itself.

Production call sites should almost never depend on RedisEntityStore
directly. Per the ISP table in the Directory Structure Addendum:
  - P2-M7 / P2-M8 / P2-M9 (detection modules)  -> BaseEntityStoreReader
  - P2-M4 (ReferenceEncoderService)            -> BaseEntityStoreWriter
Inject `RedisEntityStore(...).reader` / `.writer` (or just construct an
EntityStoreReader / EntityStoreWriter directly) into those modules so
each only sees the interface it is allowed to depend on -- constructing
a full RedisEntityStore and handing the WHOLE thing to a scoring module
would silently reintroduce the coupling ISP is meant to prevent.

This is also the name the user-facing request in this handoff calls
"DynamicEntityStore" -- `DynamicEntityStore` is kept as an import alias
below for that phrasing, but the canonical class name (matching the
Directory Structure tree: "redis_entity_store.py # class RedisEntityStore")
is RedisEntityStore.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from phase2.store.base_entity_store import BaseEntityStoreReader, BaseEntityStoreWriter
from phase2.store.entity_store_reader import EntityStoreReader
from phase2.store.entity_store_writer import EntityStoreWriter
from shared.constants import REDIS_HISTORY_LEN
from shared.types import CurrentEmbedding, EntityProfile

logger_obj: logging.Logger = logging.getLogger(__name__)


def build_redis_client(
    host_str: str = "localhost",
    port_int: int = 6379,
    db_int: int = 0,
    password_str: Optional[str] = None,
) -> Redis:
    """
    Factory for the sync redis-py client, with the one setting every
    store class in this module REQUIRES: decode_responses=False.
    Embedding bytes are raw float16; letting redis-py try to UTF-8-decode
    them would corrupt every read.
    """
    return Redis(
        host=host_str, port=port_int, db=db_int, password=password_str,
        decode_responses=False,
    )


def build_redis_client_async(
    host_str: str = "localhost",
    port_int: int = 6379,
    db_int: int = 0,
    password_str: Optional[str] = None,
) -> AsyncRedis:
    """Async counterpart of build_redis_client() -- same decode_responses=False constraint."""
    return AsyncRedis(
        host=host_str, port=port_int, db=db_int, password=password_str,
        decode_responses=False,
    )


class RedisEntityStore(BaseEntityStoreReader, BaseEntityStoreWriter):
    """
    Combined read+write facade over one Redis connection. See module
    docstring for why production scoring/writing modules should prefer
    `.reader` / `.writer` (or a standalone EntityStoreReader /
    EntityStoreWriter) over depending on this class directly.

    Parameters
    ----------
    redis_client_sync:
        Connected `redis.Redis` (decode_responses=False) -- e.g. from
        build_redis_client().
    redis_client_async:
        Connected `redis.asyncio.Redis` (decode_responses=False), or
        None if this instance will never be used on the async path.
    history_len_int:
        Max history_embeddings kept per entity (LTRIM cap), shared by
        both the reader and writer sides.
    """

    def __init__(
        self,
        redis_client_sync: Redis,
        redis_client_async: Optional[AsyncRedis] = None,
        history_len_int: int = REDIS_HISTORY_LEN,
    ) -> None:
        self.reader: EntityStoreReader = EntityStoreReader(
            redis_client_sync=redis_client_sync,
            redis_client_async=redis_client_async,
            history_len_int=history_len_int,
        )
        self.writer: EntityStoreWriter = EntityStoreWriter(
            redis_client_sync=redis_client_sync,
            history_len_int=history_len_int,
        )

    # ── BaseEntityStoreReader — delegated ────────────────────────────────────

    def fetch_current_embedding(self, entity_id: str) -> Optional[np.ndarray]:
        return self.reader.fetch_current_embedding(entity_id)

    def list_known_entity_ids(self) -> List[str]:
        return self.reader.list_known_entity_ids()

    async def fetch_current_embedding_async(self, entity_id: str) -> Optional[np.ndarray]:
        return await self.reader.fetch_current_embedding_async(entity_id)

    async def fetch_entity_profile_async(self, entity_id: str) -> Optional[EntityProfile]:
        return await self.reader.fetch_entity_profile_async(entity_id)

    # ── BaseEntityStoreWriter — delegated ────────────────────────────────────
    # NOTE: fetch_entity_profile is required by BOTH ABCs with an identical
    # signature; RedisEntityStore satisfies both by delegating to the
    # reader's implementation (the writer's fetch_entity_profile is
    # functionally identical -- it exists on EntityStoreWriter only so a
    # caller holding a bare Writer can still read-before-write its own
    # entity, see base_entity_store.py). Both paths hit the same Redis
    # keys, so it makes no observable difference which one answers here.

    def fetch_entity_profile(self, entity_id: str) -> Optional[EntityProfile]:
        return self.reader.fetch_entity_profile(entity_id)

    def write_entity_profile(self, profile: EntityProfile) -> None:
        self.writer.write_entity_profile(profile)

    def write_current_embedding(self, current_embedding: CurrentEmbedding) -> None:
        self.writer.write_current_embedding(current_embedding)

    def append_history_embedding(self, entity_id: str, new_emb: np.ndarray) -> None:
        self.writer.append_history_embedding(entity_id, new_emb)


# Alias matching the phrasing used in this handoff's request. The
# canonical name throughout the rest of the codebase (imports, the
# Directory Structure tree) remains RedisEntityStore.
DynamicEntityStore = RedisEntityStore