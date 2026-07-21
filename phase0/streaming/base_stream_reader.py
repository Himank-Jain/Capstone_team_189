"""
phase0/streaming/base_stream_reader.py
==========================================
Phase 0 · BaseStreamReader — abstract adapter interface for streaming
metric sources. Deliberately a SEPARATE implementation from
phase2/ingestion/base_ingestor.py (same ABC shape, different module) so
Phase 0 has zero import dependency on phase1/phase2/shared, per the
independence requirement in the Phase 0 Directory Structure doc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from phase0.types import MetricPoint


class BaseStreamReader(ABC):
    """
    LSP contract: every concrete subclass returns List[MetricPoint] from
    poll(), regardless of transport. AnomalyScoringWorker only ever talks
    to this interface (DIP).
    """

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def poll(self, timeout_ms: int) -> List[MetricPoint]:
        raise NotImplementedError
