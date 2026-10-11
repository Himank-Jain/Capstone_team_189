"""Read-only live connector contract and shared polling behavior."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from shared.types import RawRecord

logger = logging.getLogger(__name__)


@dataclass
class LiveIngestorConfigData:
    tenant_id: str
    cloud_provider: str
    poll_interval_sec: int = 300
    dry_run: bool = True
    max_events_per_poll: int = 1000
    credentials_cfg: Optional[dict] = None


class BaseLiveIngestor(ABC):
    def __init__(self, cfg: LiveIngestorConfigData) -> None:
        self.cfg = cfg
        self._last_poll_ts: Optional[datetime] = None
        self._oov_count = 0
        self._total_count = 0

    @abstractmethod
    def _fetch_raw_events(self, since_ts: datetime) -> list:
        raise NotImplementedError

    @abstractmethod
    def _map_to_raw_record(self, raw_event: dict) -> Optional[RawRecord]:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> bool:
        raise NotImplementedError

    def poll(self) -> List[RawRecord]:
        since_ts = self._last_poll_ts or (
            datetime.now(timezone.utc)
            - timedelta(seconds=self.cfg.poll_interval_sec)
        )
        now = datetime.now(timezone.utc)
        try:
            raw_events = self._fetch_raw_events(since_ts)
        except Exception as exc:
            logger.error(
                "live_ingestor.fetch_failed provider=%s tenant=%s error=%s",
                self.cfg.cloud_provider,
                self.cfg.tenant_id,
                exc,
            )
            return []

        records: List[RawRecord] = []
        for raw_event in raw_events[: self.cfg.max_events_per_poll]:
            try:
                record = self._map_to_raw_record(raw_event)
            except Exception as exc:
                logger.warning(
                    "live_ingestor.map_failed provider=%s error=%s",
                    self.cfg.cloud_provider,
                    exc,
                )
                continue
            if record is not None:
                records.append(record)

        self._total_count += len(raw_events)
        self._last_poll_ts = now
        if self.cfg.dry_run:
            logger.info(
                "live_ingestor.dry_run provider=%s tenant=%s would_ingest=%d",
                self.cfg.cloud_provider,
                self.cfg.tenant_id,
                len(records),
            )
            return []
        return records

    def oov_rate(self) -> float:
        return self._oov_count / self._total_count if self._total_count else 0.0
