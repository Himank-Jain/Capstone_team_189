"""
phase2/detection/async_drift_worker.py
=====================================================
P2-M8  MMD Drift Monitor — AsyncDriftWorker
CAPSTONE-189

[P2-M8 AsyncDriftWorker] (primer, Project Directory Structure §6c)
Fabricated to isolate the async/threading concern from MmdDriftMonitor's
pure detection logic (Addendum §"Fabricated Names" table). Runs
MmdDriftMonitor.compute_drift() in a ThreadPoolExecutor -- MMD is O(N^2)
and MUST NOT run on the hot inference path (ticket, "What to Watch Out
For"). Caches the resulting DriftScore in Redis with
REDIS_DRIFT_CACHE_TTL=1800s (30 min).

Design notes
------------
* This class owns exactly the concerns MmdDriftMonitor deliberately does
  NOT: threading and Redis I/O. MmdDriftMonitor stays trivially
  unit-testable with a fake reader and no thread pool involved (same
  split CosineDeviationScorer/EntityStoreReader already established).
* Cache key: `entity:{entity_id}:drift` -- follows the same
  `entity:{id}:{field}` convention as base_entity_store.py's key
  functions (current/centroid/history/stats), but is defined here rather
  than imported from there, since base_entity_store.py's docstring scopes
  it explicitly to "the wire format shared by P2-M6 reader/writer" and
  drift scores are a P2-M8 artifact, not a P2-M6 one.
* Staleness: Redis TTL expiry is the primary staleness mechanism (see
  DriftScore's docstring in shared/types.py) -- `get_cached_drift`
  returns None once the key expires, rather than this module tracking
  staleness itself. A cache MISS is the normal, expected steady state for
  "MMD hasn't been (re)computed yet for this entity" -- callers (a future
  P2-M10 AnomalyScorer) apply their own documented fallback (0.5) on None,
  same fallback value MmdDriftMonitor itself uses for insufficient data.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from redis import Redis

from phase2.detection.mmd_drift_monitor import MmdDriftMonitor
from shared.constants import REDIS_DRIFT_CACHE_TTL
from shared.types import DriftScore

logger_obj: logging.Logger = logging.getLogger(__name__)


def drift_key(entity_id: str) -> str:
    """Redis key for entity_id's cached DriftScore (STRING, JSON bytes)."""
    return f"entity:{entity_id}:drift"


def _serialize(score: DriftScore) -> bytes:
    payload = {
        "entity_id": score.entity_id,
        "drift_score": score.drift_score,
        "drift_flag": score.drift_flag,
        "computed_at": score.computed_at.isoformat(),
    }
    return json.dumps(payload).encode("utf-8")


def _deserialize(raw_bytes: bytes) -> DriftScore:
    payload = json.loads(raw_bytes.decode("utf-8"))
    return DriftScore(
        entity_id=payload["entity_id"],
        drift_score=float(payload["drift_score"]),
        drift_flag=bool(payload["drift_flag"]),
        computed_at=datetime.fromisoformat(payload["computed_at"]),
    )


class AsyncDriftWorker:
    """
    Parameters
    ----------
    drift_monitor:
        A constructed MmdDriftMonitor (pure compute, no I/O of its own).
    redis_client_sync:
        Connected `redis.Redis` (decode_responses=False -- same
        constraint as every other Redis client in this project; drift
        payloads are JSON-encoded to utf-8 bytes by this module, so a
        decode_responses=True client would double-decode them).
    cache_ttl_sec:
        Redis TTL for cached DriftScores. Default REDIS_DRIFT_CACHE_TTL
        (1800s / 30 min) per the ticket.
    max_workers:
        ThreadPoolExecutor size. MMD is CPU-bound (numpy releases the GIL
        for the bulk of the matmuls in mmd_drift_monitor.rbf_kernel_matrix),
        so a small pool is enough to keep it off the hot path without
        oversubscribing the box.
    """

    def __init__(
        self,
        drift_monitor: MmdDriftMonitor,
        redis_client_sync: Redis,
        cache_ttl_sec: int = REDIS_DRIFT_CACHE_TTL,
        max_workers: int = 4,
    ) -> None:
        self._monitor = drift_monitor
        self._redis = redis_client_sync
        self._cache_ttl_sec = cache_ttl_sec
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="mmd-drift-worker"
        )

    # ── Async path (what the ticket actually requires) ─────────────────────

    def submit_compute(self, entity_id: str) -> "Future[DriftScore]":
        """
        Schedule MmdDriftMonitor.compute_drift(entity_id) on the thread
        pool and cache the result in Redis once it finishes. Returns
        immediately with a Future -- the caller on the hot inference path
        should NOT block on it; it exists so callers that *do* want to
        wait (tests, CLI scripts) can call `.result(timeout=...)`.
        """
        future: "Future[DriftScore]" = self._executor.submit(self._compute_and_cache, entity_id)
        return future

    def get_cached_drift(self, entity_id: str) -> Optional[DriftScore]:
        """
        Non-blocking read of the last cached DriftScore for entity_id.
        Returns None if nothing has been computed yet, or the cached
        entry's TTL has expired (see this module's docstring on
        staleness). This is the method the hot inference path calls --
        it never triggers computation itself.
        """
        raw_bytes = self._redis.get(drift_key(entity_id))
        if raw_bytes is None:
            return None
        try:
            return _deserialize(raw_bytes)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            logger_obj.warning(
                "[AsyncDriftWorker] entity_id=%s cached drift payload was malformed "
                "(%s) -- treating as a cache miss", entity_id, exc,
            )
            return None

    # ── Sync convenience path (tests / CLI / cache warm-up scripts) ────────

    def compute_and_cache_sync(self, entity_id: str) -> DriftScore:
        """Run compute_drift + cache write on the CALLING thread. Never use
        this on the hot inference path -- it exists for tests and offline
        cache warm-up jobs where blocking is fine."""
        return self._compute_and_cache(entity_id)

    def _compute_and_cache(self, entity_id: str) -> DriftScore:
        score = self._monitor.compute_drift(entity_id)
        try:
            self._redis.set(drift_key(entity_id), _serialize(score), ex=self._cache_ttl_sec)
        except Exception:
            # Cache-write failure must not lose the computed score for a
            # caller blocked on the Future -- log and still return it.
            logger_obj.exception(
                "[AsyncDriftWorker] failed to cache drift score for entity_id=%s", entity_id
            )
        return score

    def shutdown(self, wait: bool = True) -> None:
        """Cleanly stop the thread pool. Call on service shutdown."""
        self._executor.shutdown(wait=wait)
