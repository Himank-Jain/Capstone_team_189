"""
phase2/ingestion/schema_validator.py
========================================
P2-M1  |  SchemaValidator — validates + normalises a raw wire-format dict
into a RawRecord, or raises so the caller can route it to the DLQ.

SRP: this class validates ONLY. It does not fetch events (BaseIngestor's
job) and does not decide what happens to invalid events (DeadLetterWriter's
job) — it just answers "is this a valid RawRecord, and if so, what is it".
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from shared.types import RawRecord

logger_obj = logging.getLogger(__name__)

# Required wire-format keys — event-based schema (mirrors AUG_REQUIRED_COLS
# minus the training-only pair_id/view columns, which don't exist on a live
# single event).
REQUIRED_FIELDS: list[str] = [
    "entity_id", "timestamp", "cloud", "entity_type", "namespace",
    "metric_name", "value",
]


class SchemaValidationError(ValueError):
    """Raised when a raw event dict fails schema validation."""


class SchemaValidator:
    """
    Validates a raw event dict (as deserialised from Kafka/Kinesis/PubSub
    JSON/Avro payloads) against the canonical event-based schema and
    returns a normalised RawRecord.
    """

    @staticmethod
    def validate(raw_event: Dict[str, Any]) -> RawRecord:
        """
        Validate and normalise one raw event dict.

        Raises
        ------
        SchemaValidationError
            If a required field is missing, the timestamp cannot be
            parsed, or value is not a finite number.
        """
        missing = [f for f in REQUIRED_FIELDS if raw_event.get(f) is None]
        if missing:
            raise SchemaValidationError(f"Missing required field(s): {missing}")

        ts_raw = raw_event["timestamp"]
        try:
            if isinstance(ts_raw, datetime):
                ts = ts_raw
            else:
                # Accept ISO8601 with 'Z' or '+00:00' suffix.
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
        except (ValueError, TypeError) as exc:
            raise SchemaValidationError(f"Unparseable timestamp: {ts_raw!r}") from exc

        try:
            value_float = float(raw_event["value"])
        except (TypeError, ValueError) as exc:
            raise SchemaValidationError(f"Non-numeric value: {raw_event['value']!r}") from exc

        if value_float != value_float or value_float in (float("inf"), float("-inf")):
            raise SchemaValidationError(f"Non-finite value: {value_float}")

        return RawRecord(
            entity_id=str(raw_event["entity_id"]),
            timestamp=ts,
            cloud=str(raw_event["cloud"]),
            entity_type=str(raw_event["entity_type"]),
            namespace=str(raw_event["namespace"]),
            metric_name=str(raw_event["metric_name"]),
            value=value_float,
        )
