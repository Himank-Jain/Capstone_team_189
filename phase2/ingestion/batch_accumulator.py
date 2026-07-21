"""
phase2/ingestion/batch_accumulator.py
=========================================
P2-M1  |  BatchAccumulator — collects validated RawRecords until the
configured window elapses, then flushes an EventBatch.

SRP: this class accumulates and flushes only. It does not poll a stream
(BaseIngestor's job) and does not validate schema (SchemaValidator's job).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional

from shared.constants import INGEST_BATCH_WIN_SEC
from shared.types import EventBatch, RawRecord

logger_obj = logging.getLogger(__name__)


class BatchAccumulator:
    """
    Thread-safe accumulator that buffers RawRecords and flushes an
    EventBatch either when window_seconds has elapsed since the last
    flush, or when flush() is called explicitly.

    Parameters
    ----------
    window_seconds:
        Flush interval in seconds. Defaults to INGEST_BATCH_WIN_SEC (300).
        Reduce for demos/dev iteration (e.g. 30).
    source:
        Label recorded on the resulting EventBatch (kafka | kinesis | pubsub).
    """

    def __init__(
        self,
        window_seconds: int = INGEST_BATCH_WIN_SEC,
        source: str = "unknown",
    ) -> None:
        self._window_seconds = window_seconds
        self._source = source
        self._buffer: List[RawRecord] = []
        self._n_invalid = 0
        self._window_start_t = time.monotonic()
        self._lock = threading.Lock()

    def add(self, record: RawRecord) -> None:
        """Append one validated record to the current window's buffer."""
        with self._lock:
            self._buffer.append(record)

    def mark_invalid(self, count: int = 1) -> None:
        """Record that `count` events failed validation this window (for
        EventBatch.n_invalid — these events themselves go to the DLQ, not
        into the buffer)."""
        with self._lock:
            self._n_invalid += count

    def should_flush(self) -> bool:
        """True once window_seconds has elapsed since the last flush."""
        return (time.monotonic() - self._window_start_t) >= self._window_seconds

    def flush(self) -> Optional[EventBatch]:
        """
        Emit the current buffer as an EventBatch and reset for the next
        window. Returns None if the buffer is empty AND there were no
        invalid events this window (nothing worth emitting).
        """
        with self._lock:
            if not self._buffer and self._n_invalid == 0:
                self._window_start_t = time.monotonic()
                return None

            batch = EventBatch(
                records=self._buffer,
                batch_ts=datetime.now(timezone.utc),
                source=self._source,
                n_invalid=self._n_invalid,
            )
            logger_obj.info(
                "[BatchAccumulator] Flushed EventBatch: %d records, %d invalid, source=%s",
                len(self._buffer), self._n_invalid, self._source,
            )
            self._buffer = []
            self._n_invalid = 0
            self._window_start_t = time.monotonic()
            return batch
