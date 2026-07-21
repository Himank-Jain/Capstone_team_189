"""
phase2/ingestion/base_ingestor.py
====================================
P2-M1  |  BaseIngestor — abstract adapter interface for streaming sources.

LSP contract: every concrete subclass must return List[RawRecord] from
poll(), regardless of the underlying transport (Kafka/Kinesis/PubSub).
BatchAccumulator and IngestionPipeline only ever talk to this interface
(DIP) — swapping KafkaIngestor for KinesisIngestor never requires a
change anywhere else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from shared.types import RawRecord


class BaseIngestor(ABC):
    """
    Abstract base for a streaming source adapter.

    Concrete subclasses (KafkaIngestor, KinesisIngestor, PubSubIngestor)
    must implement start(), stop(), and poll() with IDENTICAL signatures
    and return types so they are interchangeable (LSP).
    """

    @abstractmethod
    def start(self) -> None:
        """Open the underlying connection/subscription. Idempotent."""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """Close the underlying connection/subscription. Idempotent."""
        raise NotImplementedError

    @abstractmethod
    def poll(self, timeout_ms: int) -> List[RawRecord]:
        """
        Fetch whatever raw events are available within timeout_ms.

        Parameters
        ----------
        timeout_ms:
            Max time to block waiting for at least one event.

        Returns
        -------
        List[RawRecord]
            Possibly empty. Malformed events should be dropped by the
            adapter's own parsing step and reported via the adapter's own
            logger — final schema validation still happens centrally in
            IngestionPipeline via SchemaValidator, so adapters do not need
            to duplicate that logic, only basic wire-format parsing.
        """
        raise NotImplementedError
