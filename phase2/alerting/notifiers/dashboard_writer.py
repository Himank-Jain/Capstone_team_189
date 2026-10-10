"""
phase2/alerting/notifiers/dashboard_writer.py
==========================================
P2-M14  Explainable Alert API — DashboardWriter
CAPSTONE-189

Writes each dispatched alert to a time-series store for dashboard
visualization (ticket: "InfluxDB or PostgreSQL").

Design notes
------------
1. Store choice left to a DIP boundary, not hardcoded. Rather than pick
   one of InfluxDB/Postgres and bake its client library into this
   module, DashboardWriter depends only on BaseDashboardStore (write
   one row/point per alert). Two concrete implementations are provided:
   PostgresDashboardStore (asyncpg, a plain timestamped table) and
   InMemoryDashboardStore (a bounded deque, zero external deps — used
   by default so the API is runnable standalone per the ticket's own
   "Build the FastAPI server so it can run standalone" instruction, and
   by tests). An InfluxDB implementation follows the identical
   BaseDashboardStore shape and is intentionally not included here to
   avoid a dependency this project's requirements.txt doesn't otherwise
   need — swapping one in later touches no code outside a new
   InfluxDashboardStore class.

2. asyncpg import is deferred into PostgresDashboardStore.__init__, not
   module-level — so importing this module (e.g. for
   InMemoryDashboardStore in tests) never requires asyncpg to be
   installed at all.

3. DashboardWriter itself is a BaseNotifier (same notify() contract as
   Slack/Email/PagerDuty) so NotificationDispatcher can fan out to it
   identically -- "one more channel", not a special case.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import Any, Deque, Dict, List

from ..api.models import AlertPayloadModel
from .base_notifier import BaseNotifier


class BaseDashboardStore(ABC):
    """Write-only sink for one alert "point". Implementations decide
    the underlying storage (Postgres table, InfluxDB bucket, etc.)."""

    @abstractmethod
    async def write_alert(self, payload: AlertPayloadModel) -> str:
        """Persist one alert. Returns a short detail string (e.g. row
        id) for DispatchOutcome.detail. Raise on failure."""
        raise NotImplementedError


class InMemoryDashboardStore(BaseDashboardStore):
    """
    Zero-dependency store backed by a bounded deque — the default used
    when no real time-series store is configured, so the API remains
    runnable standalone (ticket's own requirement) and unit-testable
    without a database.
    """

    def __init__(self, max_len: int = 10_000) -> None:
        self._points: Deque[Dict[str, Any]] = deque(maxlen=max_len)

    async def write_alert(self, payload: AlertPayloadModel) -> str:
        self._points.append(
            {
                "alert_id": str(payload.alert_id),
                "entity_id": payload.entity_id,
                "batch_ts": payload.batch_ts.isoformat(),
                "final_score": payload.final_score,
                "severity": payload.severity.value,
                "sev_level": payload.sev_level.value,
                "cloud_provider": payload.cloud_provider,
                "region": payload.region,
            }
        )
        return f"in-memory row #{len(self._points)}"

    def all_points(self) -> List[Dict[str, Any]]:
        return list(self._points)


class PostgresDashboardStore(BaseDashboardStore):
    """
    Writes one row per alert into a `alerts` table via an injected
    asyncpg connection pool.

    Expected schema (create once, e.g. in an init migration):

        CREATE TABLE IF NOT EXISTS alerts (
            alert_id        UUID PRIMARY KEY,
            entity_id       TEXT NOT NULL,
            batch_ts        TIMESTAMPTZ NOT NULL,
            final_score     DOUBLE PRECISION NOT NULL,
            severity        TEXT NOT NULL,
            sev_level       TEXT NOT NULL,
            cloud_provider  TEXT NOT NULL,
            region          TEXT NOT NULL,
            target_team     TEXT NOT NULL,
            group_type      TEXT NOT NULL
        );
    """

    def __init__(self, pool: Any) -> None:
        """
        Parameters
        ----------
        pool:
            An injected asyncpg.Pool (or anything exposing an async
            `.execute(query, *args)` — DIP, testable with a fake pool).
        """
        self._pool = pool

    async def write_alert(self, payload: AlertPayloadModel) -> str:
        await self._pool.execute(
            """
            INSERT INTO alerts (
                alert_id, entity_id, batch_ts, final_score, severity,
                sev_level, cloud_provider, region, target_team, group_type
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (alert_id) DO NOTHING
            """,
            payload.alert_id,
            payload.entity_id,
            payload.batch_ts,
            payload.final_score,
            payload.severity.value,
            payload.sev_level.value,
            payload.cloud_provider,
            payload.region,
            payload.target_team,
            payload.group_type.value,
        )
        return f"postgres row alert_id={payload.alert_id}"


class DashboardWriter(BaseNotifier):
    def __init__(self, store: BaseDashboardStore) -> None:
        super().__init__(channel_name="dashboard")
        self._store = store

    async def _send(self, payload: AlertPayloadModel) -> str:
        return await self._store.write_alert(payload)
