"""
phase2/ingestion/dead_letter_writer.py
==========================================
P2-M1  |  DeadLetterWriter — writes-only interface for invalid events (ISP:
this class never reads events back; a consumer that only needs to record
failures never depends on read methods it doesn't use).

Default backend is an append-only JSONL log file. Swap for a Kafka DLQ
topic producer later without touching IngestionPipeline (DIP — the
pipeline depends on this class's write() method, not on "how a file vs.
a Kafka topic works").
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger_obj = logging.getLogger(__name__)


class DeadLetterWriter:
    """
    Appends malformed/invalid raw events to a JSONL dead-letter file,
    one JSON object per line, alongside the reason validation failed.

    Parameters
    ----------
    dlq_path:
        File path to append to. Parent directories are created if needed.
    """

    def __init__(self, dlq_path: str = "dead_letter_queue.jsonl") -> None:
        self._dlq_path = Path(dlq_path)
        self._dlq_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, raw_event: Dict[str, Any], reason: str) -> None:
        """Append one invalid event + its failure reason to the DLQ file."""
        record = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "raw_event": raw_event,
        }
        line = json.dumps(record, default=str)
        with self._lock:
            with self._dlq_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        logger_obj.warning("[DeadLetterWriter] Routed invalid event to DLQ: %s", reason)
