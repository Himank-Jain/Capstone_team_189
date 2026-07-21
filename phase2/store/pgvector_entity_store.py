"""
phase2/store/pgvector_entity_store.py
=====================================================
P2-M6  Dynamic Entity Store — PgVectorEntityStore (secondary/analytical)
CAPSTONE-189

[P2-M6 EntityStore]  (primer, Project Directory Structure §6b)
"... PgVectorEntityStore: secondary for analytical queries."

Role of this store
--------------------
Redis (RedisEntityStore) is the ONLY store on the hot inference path --
P2-M7/P2-M8/P2-M9 read from it exclusively, sub-millisecond, per
scoring call. PgVectorEntityStore is NOT part of that path. It exists
for:
  - Ad-hoc analytical SQL (e.g. "which entities had emb_variance above
    X last week", joined against other Postgres-resident tables).
  - Vector similarity queries across the FULL entity population using
    pgvector's `<->` operator + an ivfflat index, which is a poor fit
    for Redis (no native ANN index) but exactly what pgvector is for.
  - A durable, queryable audit trail of centroid history over time
    (Redis only ever holds the CURRENT centroid; this table can hold
    one row per (entity_id, last_update_ts) snapshot if the caller opts
    into `upsert_profile(..., keep_history_bool=True)`).

This class does NOT own writes into the hot path and does NOT implement
BaseEntityStoreReader/BaseEntityStoreWriter -- it is deliberately a
separate, narrower interface (GRASP: Protected Variations -- swapping
the analytical backend, or removing it entirely, must never touch
P2-M7/M8/M9). A caller (e.g. ReferenceEncoderService's periodic refresh
job, or a small sync worker) that wants profiles mirrored into Postgres
calls `pgvector_store.upsert_profile(profile)` alongside the normal
`entity_store_writer.write_entity_profile(profile)` call -- the two
stores are kept eventually consistent by the caller, not by this class.

Requires: psycopg (v3) and the `pgvector` Python package
(`pip install psycopg[binary] pgvector`), plus `CREATE EXTENSION vector;`
available on the target Postgres instance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np

try:
    import psycopg
    from pgvector.psycopg import register_vector
except ImportError:  # pragma: no cover - optional dependency, see module docstring
    psycopg = None  # type: ignore[assignment]
    register_vector = None  # type: ignore[assignment]

from shared.types import EntityProfile

logger_obj: logging.Logger = logging.getLogger(__name__)

EMB_DIM: int = 128

_CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS vector;"

_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS entity_profiles (
    entity_id           TEXT PRIMARY KEY,
    centroid_emb        VECTOR({EMB_DIM}) NOT NULL,
    emb_variance        DOUBLE PRECISION NOT NULL,
    n_records           INTEGER NOT NULL,
    last_update_ts      TIMESTAMPTZ NOT NULL,
    cold_start_flag     BOOLEAN NOT NULL DEFAULT FALSE
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS entity_profiles_centroid_ivfflat_idx
    ON entity_profiles USING ivfflat (centroid_emb vector_cosine_ops) WITH (lists = 100);
"""

# Optional append-only history table for "durable audit trail" use case.
_CREATE_HISTORY_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS entity_profile_history (
    id                  BIGSERIAL PRIMARY KEY,
    entity_id           TEXT NOT NULL,
    centroid_emb        VECTOR({EMB_DIM}) NOT NULL,
    emb_variance        DOUBLE PRECISION NOT NULL,
    n_records           INTEGER NOT NULL,
    snapshot_ts         TIMESTAMPTZ NOT NULL
);
"""
_CREATE_HISTORY_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS entity_profile_history_entity_ts_idx
    ON entity_profile_history (entity_id, snapshot_ts);
"""

_UPSERT_SQL = """
INSERT INTO entity_profiles (entity_id, centroid_emb, emb_variance, n_records,
                              last_update_ts, cold_start_flag)
VALUES (%(entity_id)s, %(centroid_emb)s, %(emb_variance)s, %(n_records)s,
        %(last_update_ts)s, %(cold_start_flag)s)
ON CONFLICT (entity_id) DO UPDATE SET
    centroid_emb    = EXCLUDED.centroid_emb,
    emb_variance    = EXCLUDED.emb_variance,
    n_records       = EXCLUDED.n_records,
    last_update_ts  = EXCLUDED.last_update_ts,
    cold_start_flag = EXCLUDED.cold_start_flag;
"""

_INSERT_HISTORY_SQL = """
INSERT INTO entity_profile_history (entity_id, centroid_emb, emb_variance, n_records, snapshot_ts)
VALUES (%(entity_id)s, %(centroid_emb)s, %(emb_variance)s, %(n_records)s, %(snapshot_ts)s);
"""

_NEAREST_ENTITIES_SQL = """
SELECT entity_id, 1 - (centroid_emb <=> %(query_emb)s) AS cosine_similarity
FROM entity_profiles
WHERE entity_id != %(exclude_entity_id)s
ORDER BY centroid_emb <=> %(query_emb)s
LIMIT %(k)s;
"""

_HIGH_VARIANCE_SQL = """
SELECT entity_id, emb_variance, n_records, last_update_ts
FROM entity_profiles
WHERE emb_variance >= %(min_variance)s
ORDER BY emb_variance DESC
LIMIT %(limit)s;
"""


@dataclass
class NearestEntityResult:
    """One row of an analytical nearest-centroid query."""
    entity_id: str
    cosine_similarity: float


class PgVectorEntityStore:
    """
    Secondary, analytics-only store. Constructor takes a DSN string
    (never a live connection) because this class is expected to be
    long-lived (e.g. a periodic sync worker) and opens/closes its own
    connections per call rather than holding one open indefinitely.

    Parameters
    ----------
    dsn_str:
        libpq connection string, e.g.
        "postgresql://user:pass@host:5432/dbname".
    """

    def __init__(self, dsn_str: str) -> None:
        if psycopg is None:
            raise ImportError(
                "[PgVectorEntityStore] psycopg and pgvector are required for this "
                "class -- pip install 'psycopg[binary]' pgvector"
            )
        self._dsn = dsn_str

    def _connect(self) -> "psycopg.Connection":
        conn = psycopg.connect(self._dsn)
        register_vector(conn)
        return conn

    # ── Schema setup ─────────────────────────────────────────────────────────

    def ensure_schema(self, with_history_table_bool: bool = False) -> None:
        """
        Idempotent DDL: enable the pgvector extension, create the
        entity_profiles table + ivfflat index, and optionally the
        append-only entity_profile_history table. Safe to call on every
        service startup.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_EXTENSION_SQL)
                cur.execute(_CREATE_TABLE_SQL)
                cur.execute(_CREATE_INDEX_SQL)
                if with_history_table_bool:
                    cur.execute(_CREATE_HISTORY_TABLE_SQL)
                    cur.execute(_CREATE_HISTORY_INDEX_SQL)
            conn.commit()
        logger_obj.info("[PgVectorEntityStore] schema ensured (with_history=%s)", with_history_table_bool)

    # ── Writes (called alongside, never instead of, EntityStoreWriter) ──────

    def upsert_profile(self, profile: EntityProfile, keep_history_bool: bool = False) -> None:
        """
        Mirror one EntityProfile into Postgres for analytical querying.
        Call this from the SAME code path that calls
        entity_store_writer.write_entity_profile(profile) (e.g.
        ReferenceEncoderService's refresh job) -- this store never reads
        from Redis itself.

        keep_history_bool:
            Also insert an immutable snapshot row into
            entity_profile_history (requires ensure_schema(with_history_table_bool=True)
            to have been called first).
        """
        centroid_emb = np.asarray(profile.centroid_emb, dtype=np.float32)
        params = {
            "entity_id": profile.entity_id,
            "centroid_emb": centroid_emb,
            "emb_variance": float(profile.emb_variance),
            "n_records": int(profile.n_records),
            "last_update_ts": profile.last_update_ts,
            "cold_start_flag": bool(profile.cold_start_flag),
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_UPSERT_SQL, params)
                if keep_history_bool:
                    cur.execute(
                        _INSERT_HISTORY_SQL,
                        {
                            "entity_id": profile.entity_id,
                            "centroid_emb": centroid_emb,
                            "emb_variance": float(profile.emb_variance),
                            "n_records": int(profile.n_records),
                            "snapshot_ts": profile.last_update_ts,
                        },
                    )
            conn.commit()

    def upsert_profiles_bulk(self, profiles: List[EntityProfile]) -> None:
        """Convenience loop over upsert_profile — one connection for the whole batch."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                for profile in profiles:
                    cur.execute(
                        _UPSERT_SQL,
                        {
                            "entity_id": profile.entity_id,
                            "centroid_emb": np.asarray(profile.centroid_emb, dtype=np.float32),
                            "emb_variance": float(profile.emb_variance),
                            "n_records": int(profile.n_records),
                            "last_update_ts": profile.last_update_ts,
                            "cold_start_flag": bool(profile.cold_start_flag),
                        },
                    )
            conn.commit()
        logger_obj.info("[PgVectorEntityStore] bulk-upserted %d profiles", len(profiles))

    # ── Analytical reads ─────────────────────────────────────────────────────

    def find_nearest_entities(
        self, query_emb: np.ndarray, exclude_entity_id: str, k_int: int = 10,
    ) -> List[NearestEntityResult]:
        """
        Cosine-nearest entities to query_emb via pgvector's `<=>` (cosine
        distance) operator + the ivfflat index. Used for things like "who
        else behaves like this entity right now" analytical dashboards --
        NOT for the hot-path EpisodeRetriever (P2-M9), which uses FAISS
        over the full historical episode corpus instead of per-entity
        centroids.
        """
        query_arr = np.asarray(query_emb, dtype=np.float32)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _NEAREST_ENTITIES_SQL,
                    {"query_emb": query_arr, "exclude_entity_id": exclude_entity_id, "k": k_int},
                )
                rows = cur.fetchall()
        return [NearestEntityResult(entity_id=row[0], cosine_similarity=float(row[1])) for row in rows]

    def find_high_variance_entities(
        self, min_variance_float: float, limit_int: int = 100,
    ) -> List[Tuple[str, float, int, datetime]]:
        """Entities with emb_variance >= min_variance_float, most volatile first."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _HIGH_VARIANCE_SQL,
                    {"min_variance": min_variance_float, "limit": limit_int},
                )
                return cur.fetchall()