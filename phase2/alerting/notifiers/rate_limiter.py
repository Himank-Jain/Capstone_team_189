"""
phase2/alerting/notifiers/rate_limiter.py
==========================================
P2-M14  Explainable Alert API — notifier rate limiting
CAPSTONE-189

Slack's webhook limit is 1 message/second (ticket's own "Watch Out
For"). Rather than bake this into SlackNotifier directly, it's a small
reusable AsyncRateLimiter any notifier can wrap itself with -- other
channels (PagerDuty Events API v2, SMTP) have their own, different
limits and can reuse the same primitive with a different
min_interval_sec instead of a Slack-specific solution creeping into
other notifiers.

Design notes
------------
1. Per-key limiting, not global. One AsyncRateLimiter instance can rate
   limit MULTIPLE independent targets (e.g. several Slack webhook URLs)
   by keying on an arbitrary string -- each key gets its own
   last-sent timestamp, so throttling one webhook never delays another.

2. asyncio.Lock per key, not a single global lock. Only calls sharing
   the same key ever serialize against each other; concurrent sends to
   different keys proceed independently. Locks are created lazily and
   never removed -- acceptable at the notifier-target cardinality this
   project runs at (a handful of webhook URLs / routing keys), not
   designed for unbounded key growth.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import DefaultDict, Dict


class AsyncRateLimiter:
    """
    Enforces at most one "pass" per `min_interval_sec` per key. Callers
    await `acquire(key)` before sending; it sleeps just long enough to
    respect the interval, then returns.

    Parameters
    ----------
    min_interval_sec:
        Minimum seconds between two acquires for the SAME key. Default
        1.0s matches Slack's documented 1 msg/sec/webhook limit.
    """

    def __init__(self, min_interval_sec: float = 1.0) -> None:
        self._min_interval_sec = min_interval_sec
        self._last_sent_at: Dict[str, float] = {}
        self._locks: DefaultDict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def acquire(self, key: str) -> None:
        async with self._locks[key]:
            now = time.monotonic()
            last = self._last_sent_at.get(key)
            if last is not None:
                elapsed = now - last
                wait_for = self._min_interval_sec - elapsed
                if wait_for > 0:
                    await asyncio.sleep(wait_for)
            self._last_sent_at[key] = time.monotonic()
