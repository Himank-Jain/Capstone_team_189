"""
phase2/store/base_entity_store.py
=====================================================
P2-M6  Dynamic Entity Store — shared ABCs, key naming, (de)serialization
CAPSTONE-189

[P2-M6 EntityStore]  (primer, Project Directory Structure §6b)
Redis primary. Keys: entity:{id}:current (float16 bytes),
entity:{id}:centroid, entity:{id}:history (List). History: LPUSH+LTRIM to
REDIS_HISTORY_LEN=30 atomically. Stats in Redis Hash. ISP:
EntityStoreReader (reads only) + EntityStoreWriter (writes only) as
separate interfaces. PgVectorEntityStore: secondary for analytical
queries. Async methods via aioredis.

Scope of this file
-------------------
This module is the "Base…" ABC layer per the nomenclature system
(§2a: "Base… — Abstract base class, never instantiated"). It owns:
  1. BaseEntityStoreReader / BaseEntityStoreWriter — the two ISP-split
     abstract interfaces. Detection modules (P2-M7, P2-M8, P2-M9) depend
     on BaseEntityStoreReader alone; ReferenceEncoderService (P2-M4)
     depends on BaseEntityStoreWriter alone (see Directory Structure
     Addendum §3, "I — Interface Segregation Principle" table).
  2. Redis key-naming and float16 (de)serialization helpers, shared by
     both concrete Redis implementations (entity_store_reader.py,
     entity_store_writer.py) so the two never drift out of sync on the
     wire format or key scheme (GRASP: Protected Variations — the key
     scheme is the point of variation, and both concrete classes go
     through this stable interface around it rather than each hardcoding
     "entity:{id}:current" independently).

Why BaseEntityStoreWriter also declares fetch_entity_profile
--------------------------------------------------------------
ReferenceEncoderService.update_profile_incremental() (P2-M4, already
built) calls `self._entity_store_writer.fetch_entity_profile(entity_id)`
to read the PRIOR profile before blending in a new EMA update — it is
never given a reader, only a writer (per the ISP table: "ReferenceEncoderService
only writes — it depends on EntityStoreWriter alone"). Read-modify-write
of an entity's OWN profile is treated as part of the writer's contract
(it is the writer that owns correctness of the mutation, not an
independent read path), whereas BaseEntityStoreReader's fetch_entity_profile
is the separate, read-only path that downstream SCORING modules (P2-M7,
P2-M8) depend on instead. The two interfaces expose the same method
name/signature by coincidence of shape, not by inheritance -- each
concrete class (EntityStoreReader, EntityStoreWriter) implements it
independently against the same Redis keys, so a caller holding only a
Writer never gains scoring-time read access to OTHER entities via some
shared reader object it was never given.

Frozen wire format
--------------------
Embeddings are always 128-d and always stored as float16 bytes
(REDIS_EMB_BYTES=256 == 128 * 2 bytes) per the Directory Structure
Addendum's constant registry. Do not change EMB_DIM or the dtype without
a team PR — every consumer (P2-M7/M8/M9) assumes this exact wire shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np

from shared.constants import REDIS_EMB_BYTES
from shared.types import CurrentEmbedding, EntityProfile

EMB_DIM: int = 128
assert REDIS_EMB_BYTES == EMB_DIM * 2, (
    "[base_entity_store] REDIS_EMB_BYTES must equal EMB_DIM * 2 (float16) -- "
    "shared/constants.py and this module have drifted apart."
)


# ─────────────────────────────────────────────────────────────────────────────
# Key naming (single source of truth — do not hardcode "entity:{id}:..."
# anywhere else in the codebase; import these instead)
# ─────────────────────────────────────────────────────────────────────────────

def current_key(entity_id: str) -> str:
    """Redis key for entity_id's current_embedding (STRING, float16 bytes)."""
    return f"entity:{entity_id}:current"


def centroid_key(entity_id: str) -> str:
    """Redis key for entity_id's centroid_ema (STRING, float16 bytes)."""
    return f"entity:{entity_id}:centroid"


def history_key(entity_id: str) -> str:
    """Redis key for entity_id's history_embeddings (LIST of float16 bytes)."""
    return f"entity:{entity_id}:history"


def stats_key(entity_id: str) -> str:
    """Redis key for entity_id's stats (HASH: last_update_ts/record_count/embedding_variance)."""
    return f"entity:{entity_id}:stats"


STATS_KEY_GLOB: str = "entity:*:stats"  # SCAN pattern used by list_known_entity_ids()


def entity_id_from_stats_key(key_str: str) -> str:
    """Inverse of stats_key() — extract entity_id from a SCAN-matched key."""
    # "entity:{id}:stats" -> {id}; entity_id itself must not contain ':'.
    return key_str[len("entity:"):-len(":stats")]


# ─────────────────────────────────────────────────────────────────────────────
# (De)serialization — float16 wire format
# ─────────────────────────────────────────────────────────────────────────────

def serialize_emb_f16(emb: np.ndarray) -> bytes:
    """
    Cast an embedding (any float dtype, shape (EMB_DIM,)) down to float16
    and return its raw bytes for storage as a Redis STRING or LIST
    element. Callers pass L2-normalised float32 vectors (per
    shared/types.py contracts); precision loss from the float16 cast is
    accepted project-wide (REDIS_EMB_BYTES=256 == 128*float16).
    """
    emb_arr = np.asarray(emb, dtype=np.float32)
    if emb_arr.shape != (EMB_DIM,):
        raise ValueError(
            f"[base_entity_store] embedding must be shape ({EMB_DIM},), got {emb_arr.shape}"
        )
    return emb_arr.astype(np.float16).tobytes()


def deserialize_emb_f16(raw_bytes: bytes) -> np.ndarray:
    """
    Inverse of serialize_emb_f16(). Returns float32 (EMB_DIM,) — every
    downstream consumer (cosine scoring, MMD, FAISS) does its math in
    float32; the float16 cast is a storage-only compression choice.
    """
    emb_f16 = np.frombuffer(raw_bytes, dtype=np.float16)
    if emb_f16.shape != (EMB_DIM,):
        raise ValueError(
            f"[base_entity_store] decoded embedding must be shape ({EMB_DIM},), "
            f"got {emb_f16.shape} (raw byte count={len(raw_bytes)})"
        )
    return emb_f16.astype(np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# ISP-split ABCs
# ─────────────────────────────────────────────────────────────────────────────

class BaseEntityStoreReader(ABC):
    """
    Read-only interface over the entity store. P2-M7 (CosineDeviationScorer),
    P2-M8 (MmdDriftMonitor), and P2-M9 (EpisodeRetriever) depend on this
    ABC alone — never on BaseEntityStoreWriter (ISP).
    """

    @abstractmethod
    def fetch_entity_profile(self, entity_id: str) -> Optional[EntityProfile]:
        """Return entity_id's EntityProfile, or None if it has never been written."""
        raise NotImplementedError

    @abstractmethod
    def fetch_current_embedding(self, entity_id: str) -> Optional[np.ndarray]:
        """Return entity_id's current_embedding (EMB_DIM,) float32, or None."""
        raise NotImplementedError

    @abstractmethod
    def list_known_entity_ids(self) -> List[str]:
        """Return every entity_id that currently has a stored profile/stats hash."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_entity_profile_async(self, entity_id: str) -> Optional[EntityProfile]:
        """Async counterpart of fetch_entity_profile — high-throughput inference path."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_current_embedding_async(self, entity_id: str) -> Optional[np.ndarray]:
        """Async counterpart of fetch_current_embedding — high-throughput inference path."""
        raise NotImplementedError


class BaseEntityStoreWriter(ABC):
    """
    Write-only interface over the entity store (plus the read-modify-write
    `fetch_entity_profile` needed to blend an EMA update — see this
    module's docstring, "Why BaseEntityStoreWriter also declares
    fetch_entity_profile"). ReferenceEncoderService (P2-M4) depends on
    this ABC alone.
    """

    @abstractmethod
    def fetch_entity_profile(self, entity_id: str) -> Optional[EntityProfile]:
        """Read entity_id's current profile before blending in an EMA update."""
        raise NotImplementedError

    @abstractmethod
    def write_entity_profile(self, profile: EntityProfile) -> None:
        """
        Persist a full EntityProfile: centroid_ema, history_embeddings
        (replacing the stored list, oldest-first), and the stats hash.
        """
        raise NotImplementedError

    @abstractmethod
    def write_current_embedding(self, current_embedding: CurrentEmbedding) -> None:
        """Persist entity_id's current_embedding for this ingestion batch."""
        raise NotImplementedError

    @abstractmethod
    def append_history_embedding(self, entity_id: str, new_emb: np.ndarray) -> None:
        """
        Atomically push ONE new window-embedding onto entity_id's history
        (LPUSH + LTRIM), without rewriting the whole profile. Exposed
        separately from write_entity_profile for callers that only have
        a single incremental embedding and don't want to re-derive
        centroid/variance themselves.
        """
        raise NotImplementedError