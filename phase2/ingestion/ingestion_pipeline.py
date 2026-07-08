"""
phase2/ingestion/ingestion_pipeline.py
==========================================
P2-M1  |  IngestionPipeline — Controller (GRASP) that wires a BaseIngestor,
BatchAccumulator, and DeadLetterWriter into one runnable poll → accumulate
→ flush cycle.

This is the class other modules actually instantiate; they never talk to
BaseIngestor/BatchAccumulator directly.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from phase2.ingestion.base_ingestor import BaseIngestor
from phase2.ingestion.batch_accumulator import BatchAccumulator
from shared.constants import INGEST_BATCH_WIN_SEC, INGEST_POLL_MS
from shared.types import EventBatch

logger_obj = logging.getLogger(__name__)


class IngestionPipeline:
    """
    Runs the ingest → accumulate → flush cycle for one BaseIngestor.

    Parameters
    ----------
    ingestor:
        Any BaseIngestor implementation (Kafka/Kinesis/PubSub) — DIP.
    on_batch:
        Callback invoked with each flushed EventBatch (e.g. hand off to
        P2-M2 RecordEncoder / a queue). Never crashes the pipeline if it
        raises — the exception is logged and polling continues, per
        "never crash on bad events".
    window_seconds:
        Batch flush interval. Defaults to INGEST_BATCH_WIN_SEC (300s);
        pass a smaller value (e.g. 30) for demos/dev iteration.
    poll_timeout_ms:
        Per-poll() timeout passed to the ingestor.
    source_label:
        Recorded on each EventBatch (kafka | kinesis | pubsub).
    """

    def __init__(
        self,
        ingestor: BaseIngestor,
        on_batch: Callable[[EventBatch], None],
        window_seconds: int = INGEST_BATCH_WIN_SEC,
        poll_timeout_ms: int = INGEST_POLL_MS,
        source_label: str = "unknown",
    ) -> None:
        self._ingestor = ingestor
        self._on_batch = on_batch
        self._poll_timeout_ms = poll_timeout_ms
        self._accumulator = BatchAccumulator(window_seconds=window_seconds, source=source_label)
        self._running = False

        # Health metrics (P2-M1 "add health metrics" requirement)
        self.events_received_total: int = 0
        self.validation_errors_total: int = 0

    def stop(self) -> None:
        self._running = False
        self._ingestor.stop()
        logger_obj.info("[IngestionPipeline] Stopped")

    async def start_async(self) -> None:
        """
        Poll continuously, accumulating records and flushing an EventBatch
        (via on_batch) whenever the accumulator's window elapses.

        A malformed poll cycle (ingestor exception, callback exception)
        is logged and the loop continues — ingestion must never crash on
        bad input.
        """
        self._ingestor.start()
        self._running = True
        logger_obj.info("[IngestionPipeline] Starting poll loop")

        while self._running:
            try:
                records = self._ingestor.poll(timeout_ms=self._poll_timeout_ms)
                invalid_count = getattr(self._ingestor, "last_poll_invalid_count", 0)

                self.events_received_total += len(records) + invalid_count
                self.validation_errors_total += invalid_count

                for record in records:
                    self._accumulator.add(record)
                if invalid_count:
                    self._accumulator.mark_invalid(invalid_count)

            except Exception:
                logger_obj.exception("[IngestionPipeline] poll() cycle failed — continuing")

            if self._accumulator.should_flush():
                try:
                    batch = self._accumulator.flush()
                    if batch is not None:
                        self._on_batch(batch)
                except Exception:
                    logger_obj.exception("[IngestionPipeline] on_batch callback failed — continuing")

            await asyncio.sleep(0)  # yield control; poll() itself blocks up to poll_timeout_ms

    @property
    def validation_error_rate(self) -> float:
        """events_received/s and batch_lag_seconds are left to an external
        metrics exporter (Prometheus, etc.) reading these counters; this
        property gives the one ratio worth computing locally."""
        if self.events_received_total == 0:
            return 0.0
        return self.validation_errors_total / self.events_received_total
