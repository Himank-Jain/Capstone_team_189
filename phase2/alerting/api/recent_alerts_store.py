"""
phase2/alerting/api/recent_alerts_store.py
==========================================
P2-M14  Explainable Alert API — RecentAlertsStore
CAPSTONE-189

Backs GET /alerts/recent (ticket: "returns last 100 alerts from Redis
sorted set").

Design notes
------------
1. Redis client injection (DIP). Same pattern as AlertDeduplicator /
   EpisodeRetriever — accepts any redis-py-compatible client
   (real redis.Redis or fakeredis.FakeStrictRedis). Pass redis_client=
   None to fall back to an in-memory bounded list, keeping the API
   runnable standalone without Redis (ticket's own requirement, same
   rationale as InMemoryDashboardStore).

2. Sorted set, scored by batch_ts epoch seconds. ZADD with the alert's
   own batch_ts as score (not insertion order) means recent-N queries
   are correct even if alerts arrive slightly out of order across
   concurrent requests. ZREMRANGEBYRANK trims the set back down after
   each insert so it never grows unbounded — capped at
   `max_len` (default 1000, ticket only ever reads the most recent 100
   of these).
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from .models import AlertPayloadModel

_REDIS_KEY = "alerts:recent"


class RecentAlertsStore:
    def __init__(self, redis_client: Optional[Any] = None, max_len: int = 1000) -> None:
        self._redis = redis_client
        self._max_len = max_len
        self._in_memory: List[str] = []  # used only when redis_client is None

    async def add(self, payload: AlertPayloadModel) -> None:
        serialized = payload.model_dump_json()
        score = payload.batch_ts.timestamp()

        if self._redis is not None:
            pipe = self._redis.pipeline()
            pipe.zadd(_REDIS_KEY, {serialized: score})
            pipe.zremrangebyrank(_REDIS_KEY, 0, -(self._max_len + 1))
            result = pipe.execute()
            if hasattr(result, "__await__"):
                await result
            return

        self._in_memory.append(serialized)
        if len(self._in_memory) > self._max_len:
            self._in_memory = self._in_memory[-self._max_len :]

    async def get_recent(self, n: int = 100) -> List[dict]:
        if self._redis is not None:
            raw_members = self._redis.zrevrange(_REDIS_KEY, 0, n - 1)
            if hasattr(raw_members, "__await__"):
                raw_members = await raw_members
            return [json.loads(m) for m in raw_members]

        return [json.loads(m) for m in reversed(self._in_memory[-n:])]
