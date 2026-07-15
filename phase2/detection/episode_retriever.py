"""
phase2/detection/episode_retriever.py
==========================================
P2-M9  Retrieved Similar Episodes — EpisodeRetriever
CAPSTONE-189

Given the current embedding of an entity, retrieves the Top-K most
similar historical episodes from the FAISS index (P1-M5, loaded via
ArtifactBundle P1-M6).

Real-data notes (found by inspecting the actual FaissIndexer /
behavioral_space_meta.pkl, not assumed from the planner prose alone)
----------------------------------------------------------------------
1. FaissIndexer.search_topk() already returns SQUARED L2 distance (its
   own docstring confirms this). For L2-normalised vectors,
   ||a-b||^2 = 2 - 2*cos_sim, so the correct conversion is
   sim = 1 - dist/2 — NOT 1 - dist**2/2 (that would square an
   already-squared value).
2. The real FAISS metadata dicts carry entity_id / timestamp /
   cloud_provider / severity_label — there is NO incident_id/episode_id
   field. This class synthesizes episode_id from the FAISS internal
   vector index position, which FaissIndexer's own docstring guarantees
   is stable (vectors are only ever appended, never reordered/removed).
3. severity_label is commonly None in the real corpus — EpisodeSearchResult
   models this as Optional rather than assuming it's always populated.

Caching
-------
Query results are cached in Redis keyed by
f"episode:{entity_id}:{embedding_hash[:8]}" with a
EPISODE_CACHE_TTL_SEC (1800s / 30min) TTL, per the planner. Cache is
optional — pass redis_client=None to disable it entirely (e.g. in tests).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import List, Optional

import numpy as np

from phase1.embedding_space.faiss_indexer import FaissIndexer
from shared.constants import EPISODE_CACHE_TTL_SEC, FAISS_TOP_K
from shared.types import EpisodeSearchResult

logger_obj: logging.Logger = logging.getLogger(__name__)


class EpisodeRetriever:
    """
    Parameters
    ----------
    faiss_indexer:
        An already-loaded FaissIndexer (e.g. from
        ArtifactBundle.load_latest()) — DIP, matching the pattern
        established by InferenceEncoder/BatchEncoder in this codebase.
        Loaded ONCE at service startup, not per-request (planner's own
        "watch out for" — the index can be hundreds of MB).
    redis_client:
        Optional redis-py-compatible client for query-result caching.
        Pass None to disable caching entirely.
    cache_ttl_sec:
        Cache entry lifetime. Defaults to EPISODE_CACHE_TTL_SEC (1800s).
    """

    def __init__(
        self,
        faiss_indexer: FaissIndexer,
        redis_client=None,
        cache_ttl_sec: int = EPISODE_CACHE_TTL_SEC,
    ) -> None:
        self._faiss_indexer = faiss_indexer
        self._redis = redis_client
        self._cache_ttl_sec = cache_ttl_sec

    # ── Cache key helper ─────────────────────────────────────────────────────

    @staticmethod
    def _embedding_hash(embedding: np.ndarray) -> str:
        """Short, stable hash of an embedding's bytes — used only for the
        cache key, never for correctness-sensitive comparisons."""
        return hashlib.sha256(np.ascontiguousarray(embedding, dtype=np.float32).tobytes()).hexdigest()

    def _cache_key(self, entity_id: str, embedding: np.ndarray) -> str:
        return f"episode:{entity_id}:{self._embedding_hash(embedding)[:8]}"

    # ── Distance -> similarity ───────────────────────────────────────────────

    @staticmethod
    def _squared_l2_to_cosine_similarity(squared_l2_distance: float) -> float:
        """
        For L2-normalised vectors: ||a-b||^2 = 2 - 2*cos_sim
        => cos_sim = 1 - ||a-b||^2 / 2

        FaissIndexer.search_topk() already returns SQUARED L2 distance
        (confirmed from its own docstring) — do not square this value
        again.
        """
        return 1.0 - (squared_l2_distance / 2.0)

    # ── Result assembly ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_timestamp(raw_ts) -> Optional[datetime]:
        if raw_ts is None:
            return None
        if isinstance(raw_ts, datetime):
            return raw_ts
        try:
            return datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _to_episode_search_result(
        self, faiss_internal_id: int, squared_l2_distance: float, metadata: Optional[dict],
    ) -> Optional[EpisodeSearchResult]:
        if metadata is None:
            return None  # -1 index slot (k exceeded ntotal, or too few IVF cells probed)

        return EpisodeSearchResult(
            similarity_score=self._squared_l2_to_cosine_similarity(float(squared_l2_distance)),
            episode_id=str(faiss_internal_id),  # synthesized — see module docstring note 2
            entity_id=metadata["entity_id"],
            timestamp=self._parse_timestamp(metadata.get("timestamp")),
            cloud_provider=metadata.get("cloud_provider", "Unknown"),
            severity_label=metadata.get("severity_label"),
        )

    # ── Public API ───────────────────────────────────────────────────────────

    def search(
        self,
        query_embedding: np.ndarray,
        k: int = FAISS_TOP_K,
        exclude_entity_id: Optional[str] = None,
    ) -> List[EpisodeSearchResult]:
        """
        Retrieve the top-k most similar historical episodes to
        `query_embedding`.

        Parameters
        ----------
        query_embedding:
            Shape (128,), L2-normalised — typically a CurrentEmbedding.emb.
        k:
            Number of neighbours to return AFTER self-retrieval filtering.
            Internally over-fetches (k + a margin) from FAISS so that
            filtering out the querying entity's own episodes doesn't
            silently under-fill the result below k.
        exclude_entity_id:
            If given, episodes belonging to this entity_id are filtered
            out (planner: "prevent self-retrieval bias" — a training
            entity would otherwise always find itself as the top match).

        Returns
        -------
        List[EpisodeSearchResult]
            Up to k results, ordered most-similar first. May be fewer
            than k if the index has too few vectors, or if the
            over-fetch margin still wasn't enough after self-filtering
            (rare — logged when it happens).
        """
        cache_key = None
        if self._redis is not None:
            cache_key = self._cache_key(exclude_entity_id or "unknown", query_embedding)
            cached = self._redis.get(cache_key)
            if cached is not None:
                payload = json.loads(cached)
                return [
                    EpisodeSearchResult(
                        similarity_score=r["similarity_score"],
                        episode_id=r["episode_id"],
                        entity_id=r["entity_id"],
                        timestamp=self._parse_timestamp(r["timestamp"]),
                        cloud_provider=r["cloud_provider"],
                        severity_label=r["severity_label"],
                    )
                    for r in payload
                ]

        # Over-fetch to survive self-filtering without under-filling k.
        fetch_k = k + 5 if exclude_entity_id else k
        fetch_k = min(fetch_k, self._faiss_indexer.index.ntotal)

        distances, indices, metadata_rows = self._faiss_indexer.search_topk(query_embedding, k=fetch_k)

        results: List[EpisodeSearchResult] = []
        for faiss_id, dist, meta in zip(indices[0], distances[0], metadata_rows[0]):
            if meta is not None and exclude_entity_id is not None and meta.get("entity_id") == exclude_entity_id:
                continue
            result = self._to_episode_search_result(int(faiss_id), float(dist), meta)
            if result is not None:
                results.append(result)
            if len(results) >= k:
                break

        if exclude_entity_id is not None and len(results) < k:
            logger_obj.debug(
                "[EpisodeRetriever] Only %d/%d results survived self-filtering for "
                "entity_id=%s — consider a larger over-fetch margin.",
                len(results), k, exclude_entity_id,
            )

        if self._redis is not None and cache_key is not None:
            serializable = [
                {
                    "similarity_score": r.similarity_score, "episode_id": r.episode_id,
                    "entity_id": r.entity_id,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "cloud_provider": r.cloud_provider, "severity_label": r.severity_label,
                }
                for r in results
            ]
            self._redis.set(cache_key, json.dumps(serializable), ex=self._cache_ttl_sec)

        return results

    def batch_search(
        self,
        query_embeddings: np.ndarray,
        k: int = FAISS_TOP_K,
        exclude_entity_ids: Optional[List[Optional[str]]] = None,
    ) -> List[List[EpisodeSearchResult]]:
        """
        Vectorized batch search for throughput — runs one FAISS call for
        the whole batch rather than N separate calls, then applies
        per-query self-filtering in Python.

        Parameters
        ----------
        query_embeddings:
            Shape (Q, 128).
        k:
            Results per query, after self-filtering.
        exclude_entity_ids:
            Length-Q list, entity_id to exclude per query (or None per
            query to exclude nothing). If omitted, no self-filtering is
            applied to any query.

        Returns
        -------
        List[List[EpisodeSearchResult]]
            Length Q, one result list per query.

        Note
        ----
        This method does NOT use the Redis cache — caching is keyed
        per-entity in `search()`, and batched queries typically represent
        a fresh multi-entity ingestion batch where cache hits would be
        rare. Call `search()` per-entity instead if cache reuse matters
        more than batch throughput for your use case.
        """
        n = query_embeddings.shape[0]
        exclude_list = exclude_entity_ids or [None] * n

        has_any_exclusion = any(e is not None for e in exclude_list)
        fetch_k = (k + 5) if has_any_exclusion else k
        fetch_k = min(fetch_k, self._faiss_indexer.index.ntotal)

        distances, indices, metadata_rows = self._faiss_indexer.search_topk(query_embeddings, k=fetch_k)

        all_results: List[List[EpisodeSearchResult]] = []
        for row_idx in range(n):
            exclude_entity_id = exclude_list[row_idx]
            row_results: List[EpisodeSearchResult] = []
            for faiss_id, dist, meta in zip(indices[row_idx], distances[row_idx], metadata_rows[row_idx]):
                if meta is not None and exclude_entity_id is not None and meta.get("entity_id") == exclude_entity_id:
                    continue
                result = self._to_episode_search_result(int(faiss_id), float(dist), meta)
                if result is not None:
                    row_results.append(result)
                if len(row_results) >= k:
                    break
            all_results.append(row_results)

        return all_results
