"""
phase2/alerting/alert_deduplicator.py
==========================================
P2-M11  Deduplication — AlertDeduplicator
CAPSTONE-189

Prevents alert storms by deduplicating AnomalyResults within a
configurable time window (default DEDUP_WINDOW_SEC=300s) per entity.

Design notes — deviations from the literal ticket text, and why
------------------------------------------------------------------
1. Fingerprint inputs. The ticket's AI Prompt Brief lists
   (entity_id, severity_level, top_features_sorted_tuple, cloud_provider)
   as fingerprint inputs. AnomalyResult (P2-M10's actual, real output
   type) carries no cloud_provider field at all — it was never part of
   that dataclass. The fingerprint here uses only what AnomalyResult
   genuinely has: entity_id, severity, and the three contribution scores
   (deviation/drift/similarity), which are AnomalyResult's own equivalent
   of "top features."

2. "Similarity > 0.9" duplicate threshold. AnomalyResult exposes three
   continuous floats, not a token/set representation — true MinHash or
   SimHash Jaccard similarity needs the latter. Rather than fake a
   similarity metric with no real set to compare, each contribution is
   rounded to DEDUP_FEATURE_BUCKET_SIZE (0.1) before hashing: firings
   whose contributions land in the same coarse buckets collapse to an
   IDENTICAL fingerprint, which is a practical stand-in for "near-
   duplicate enough" without pretending to compute a similarity score
   this data doesn't support.

3. One tracked incident per (entity_id, window), not per fingerprint.
   The ticket's own Redis key spec is dedup:{entity_id}:{window_bucket}
   — entity+window, with no fingerprint in the key. This means if a
   SECOND, genuinely different anomaly (different fingerprint) fires for
   the same entity within the same still-open window, it overwrites the
   tracked incident for that window rather than being tracked
   separately. This is a real, documented simplification — the common
   "alert storm" case (the same underlying issue firing repeatedly) is
   handled correctly; a same-entity, same-window, genuinely-different
   anomaly is a rarer edge case not explicitly resolved by the ticket,
   and is left as a known limitation rather than silently guessed at.

4. Concurrency. Multiple ingestion-pipeline workers could call check()
   for the same entity concurrently. Uses the same WATCH/MULTI/EXEC
   optimistic-locking pattern already proven correct (and stress-tested
   at 1,600 concurrent updates with zero lost writes) in Phase 0's
   RollingBaselineStore — not reinvented here.

Import constraint
-------------------
Same rule as P2-M7/M8/M9/M10: imports ONLY from shared/types.py and
shared/constants.py, plus stdlib (redis-py client is INJECTED, never
imported/constructed internally) — DIP, testable with fakeredis or a
real client identically.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from shared.constants import DEDUP_FEATURE_BUCKET_SIZE, DEDUP_WINDOW_SEC
from shared.types import AnomalyResult, DedupResult

logger_obj: logging.Logger = logging.getLogger(__name__)

MAX_WATCH_RETRIES = 100
BACKOFF_BASE_SECONDS = 0.001
BACKOFF_CAP_SECONDS = 0.05


class AlertDeduplicator:
    """
    Parameters
    ----------
    redis_client:
        Any redis-py-compatible client (real redis.Redis or
        fakeredis.FakeStrictRedis) — injected, not constructed internally.
    window_seconds:
        Dedup window AND Redis key TTL — deliberately the SAME value
        (see module docstring, note 1). Pass a shorter value for critical
        entities per-call via `window_seconds` override on check(), not
        via a second global constant.
    feature_bucket_size:
        Rounding granularity applied to each contribution score before
        fingerprinting (see module docstring, note 2).
    """

    def __init__(
        self,
        redis_client,
        window_seconds: int = DEDUP_WINDOW_SEC,
        feature_bucket_size: float = DEDUP_FEATURE_BUCKET_SIZE,
    ) -> None:
        self._redis = redis_client
        self._window_seconds = window_seconds
        self._feature_bucket_size = feature_bucket_size

    # ── Fingerprinting ───────────────────────────────────────────────────────

    def _bucket(self, value: float) -> float:
        return round(value / self._feature_bucket_size) * self._feature_bucket_size

    def _compute_fingerprint(self, anomaly_result: AnomalyResult) -> str:
        """
        Stable 64-bit-equivalent hex digest from
        (entity_id, severity, bucketed deviation/drift/similarity
        contributions). Uses hashlib (per the ticket's own "hashlib or
        mmh3" instruction) — NOT Python's built-in hash(), which is
        randomly salted per-process for strings and would never produce
        a stable fingerprint across separate worker processes.
        """
        parts = (
            anomaly_result.entity_id,
            anomaly_result.severity.value,
            f"{self._bucket(anomaly_result.deviation_contribution):.2f}",
            f"{self._bucket(anomaly_result.drift_contribution):.2f}",
            f"{self._bucket(anomaly_result.similarity_contribution):.2f}",
        )
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
        return digest[:16]  # 64 bits of hex, matching the ticket's "64-bit fingerprint"

    def _window_bucket(self, ts: datetime, window_seconds: int) -> int:
        epoch_seconds = ts.timestamp()
        return int(epoch_seconds // window_seconds) * window_seconds

    def _redis_key(self, entity_id: str, window_bucket: int) -> str:
        return f"dedup:{entity_id}:{window_bucket}"

    # ── Public API ───────────────────────────────────────────────────────────

    def check(
        self,
        anomaly_result: AnomalyResult,
        window_seconds: Optional[int] = None,
    ) -> DedupResult:
        """
        Check whether `anomaly_result` is a duplicate of an already-open
        incident for its entity within the current dedup window, or the
        start of a new one.

        Parameters
        ----------
        anomaly_result:
            The P2-M10 output to check.
        window_seconds:
            Per-call override (e.g. a shorter window for a known-critical
            entity). Defaults to the instance's configured window.

        Returns
        -------
        DedupResult
        """
        effective_window = window_seconds if window_seconds is not None else self._window_seconds
        fingerprint = self._compute_fingerprint(anomaly_result)
        window_bucket = self._window_bucket(anomaly_result.batch_ts, effective_window)
        redis_key = self._redis_key(anomaly_result.entity_id, window_bucket)

        for attempt in range(MAX_WATCH_RETRIES):
            with self._redis.pipeline() as pipe:
                try:
                    pipe.watch(redis_key)
                    raw = pipe.get(redis_key)
                    existing = json.loads(raw) if raw is not None else None

                    if existing is not None and existing["fingerprint"] == fingerprint:
                        new_recurrence_count = existing["recurrence_count"] + 1
                        payload = {
                            "canonical_incident_id": existing["canonical_incident_id"],
                            "first_seen_ts": existing["first_seen_ts"],
                            "fingerprint": fingerprint,
                            "recurrence_count": new_recurrence_count,
                        }
                        pipe.multi()
                        pipe.set(redis_key, json.dumps(payload), keepttl=True)
                        pipe.execute()

                        return DedupResult(
                            entity_id=anomaly_result.entity_id,
                            is_duplicate=True,
                            canonical_incident_id=existing["canonical_incident_id"],
                            first_seen_ts=datetime.fromisoformat(existing["first_seen_ts"]),
                            recurrence_count=new_recurrence_count,
                        )

                    new_incident_id = str(uuid.uuid4())
                    first_seen_ts = anomaly_result.batch_ts
                    payload = {
                        "canonical_incident_id": new_incident_id,
                        "first_seen_ts": first_seen_ts.isoformat(),
                        "fingerprint": fingerprint,
                        "recurrence_count": 1,
                    }
                    pipe.multi()
                    pipe.set(redis_key, json.dumps(payload), ex=effective_window)
                    pipe.execute()

                    return DedupResult(
                        entity_id=anomaly_result.entity_id,
                        is_duplicate=False,
                        canonical_incident_id=new_incident_id,
                        first_seen_ts=first_seen_ts,
                        recurrence_count=1,
                    )

                except Exception as exc:
                    if type(exc).__name__ != "WatchError":
                        raise
                    backoff = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** attempt))
                    time.sleep(random.uniform(0, backoff))
                    continue

        raise RuntimeError(
            f"[AlertDeduplicator] Failed to check {redis_key} after "
            f"{MAX_WATCH_RETRIES} WATCH retries — unexpectedly high contention"
        )
