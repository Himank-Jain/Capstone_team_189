from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List

from shared.types import RawRecord


class BaseHistoricalRecordProvider(ABC):
    @abstractmethod
    def fetch_historical_records(
        self,
        entity_id: str,
        start_ts: datetime,
        end_ts: datetime,
    ) -> List[RawRecord]:
        """Fetch historical records for an entity within the specified time window."""
        pass
