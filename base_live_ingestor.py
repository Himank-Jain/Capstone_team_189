"""
BaseLiveIngestor
-----------------
Abstract base for read-only, real-account cloud connectors.

Contract mirrors phase2/ingestion/base_ingestor.py::BaseIngestor.poll() so that
a Live*Ingestor is a drop-in alternative to DemoIngestor / KafkaIngestor at the
IngestionPipeline boundary. Nothing downstream of poll() needs to know or care
whether records came from a synthetic generator or a real account.

CRITICAL SAFETY RULE: subclasses may only ever call read-only / describe / list /
get-style SDK methods. Never call a create/put/delete/modify method here, even
transitively. IAM policy is the primary enforcement layer (see
live_ingestion/iam_policies/); this class-level rule is defense-in-depth.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from shared.types import RawRecord  # existing, frozen contract — do not modify

logger = logging.getLogger(__name__)


@dataclass
class LiveIngestorConfigData:
    """Config for one Live*Ingestor instance. One instance = one provider = one tenant."""
    tenant_id: str
    cloud_provider: str            # 'AWS' | 'Azure' | 'GCP' | 'OCI'
    poll_interval_sec: int = 300   # matches INGEST_BATCH_WIN_SEC default
    dry_run: bool = True           # ALWAYS default true; caller must explicitly opt out
    max_events_per_poll: int = 1000
    credentials_cfg: Optional[dict] = None  # provider-specific, loaded from secrets, never logged


class BaseLiveIngestor(ABC):
    """One instance polls exactly one (tenant, cloud_provider) pair."""

    def __init__(self, cfg: LiveIngestorConfigData):
        self.cfg = cfg
        self._last_poll_ts: Optional[datetime] = None
        self._oov_count = 0
        self._total_count = 0

    # ---- required by every provider connector -----------------------------

    @abstractmethod
    def _fetch_raw_events(self, since_ts: datetime) -> list:
        """Provider-SDK-specific: return raw provider events since `since_ts`.
        Must only call read-only SDK methods (Describe*/List*/Get*/LookupEvents)."""
        raise NotImplementedError

    @abstractmethod
    def _map_to_raw_record(self, raw_event: dict) -> Optional[RawRecord]:
        """Provider-specific field mapping -> RawRecord. Return None to skip
        (e.g. event type not relevant to behavioral modeling)."""
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> bool:
        """Cheap read-only call to verify credentials/connectivity. Called by
        the Settings > Live Sources UI and before activating a new connector."""
        raise NotImplementedError

    # ---- shared, provider-agnostic logic -----------------------------------

    def poll(self) -> List[RawRecord]:
        since_ts = self._last_poll_ts or self._default_lookback()
        now = datetime.now(timezone.utc)

        try:
            raw_events = self._fetch_raw_events(since_ts)
        except Exception as exc:  # never crash the ingestion pipeline on a provider API error
            logger.error(
                "live_ingestor.fetch_failed provider=%s tenant=%s error=%s",
                self.cfg.cloud_provider, self.cfg.tenant_id, exc,
            )
            return []

        raw_events = raw_events[: self.cfg.max_events_per_poll]
        records: List[RawRecord] = []

        for raw_event in raw_events:
            try:
                record = self._map_to_raw_record(raw_event)
            except Exception as exc:
                logger.warning(
                    "live_ingestor.map_failed provider=%s error=%s", self.cfg.cloud_provider, exc
                )
                continue  # route to DeadLetterWriter at the pipeline level, never crash here
            if record is not None:
                records.append(record)

        self._total_count += len(raw_events)
        self._last_poll_ts = now

        if self.cfg.dry_run:
            logger.info(
                "live_ingestor.dry_run provider=%s tenant=%s would_ingest=%d",
                self.cfg.cloud_provider, self.cfg.tenant_id, len(records),
            )
            return []  # dry-run: never actually hand records to the pipeline

        logger.info(
            "live_ingestor.poll provider=%s tenant=%s ingested=%d",
            self.cfg.cloud_provider, self.cfg.tenant_id, len(records),
        )
        return records

    def oov_rate(self) -> float:
        """Fraction of mapped records whose categorical fields fell back to <UNK>.
        Surfaced on Model Health (Section 2.11 / 3) as a live-tenant warning signal."""
        if self._total_count == 0:
            return 0.0
        return self._oov_count / self._total_count

    def _default_lookback(self) -> datetime:
        # first poll ever: look back one poll interval, not the full history,
        # to avoid a huge first batch against a real account's audit log.
        from datetime import timedelta
        return datetime.now(timezone.utc) - timedelta(seconds=self.cfg.poll_interval_sec)
