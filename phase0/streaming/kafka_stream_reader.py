"""
phase0/streaming/kafka_stream_reader.py
===========================================
Phase 0 · KafkaStreamReader(BaseStreamReader) — confluent-kafka wrapper,
self-contained (no dependency on phase2/ingestion/kafka_ingestor.py, even
though the pattern is intentionally similar).

Expected wire format (JSON): {"vm_id": str, "metric_name": str,
"timestamp": ISO8601 str, "value": float}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from phase0.streaming.base_stream_reader import BaseStreamReader
from phase0.types import MetricPoint

logger_obj = logging.getLogger(__name__)

REQUIRED_FIELDS = ["vm_id", "metric_name", "timestamp", "value"]


class KafkaStreamReader(BaseStreamReader):
    """
    Parameters
    ----------
    auto_offset_reset:
        "earliest" (default) — see the hard-won lesson from Phase 2's
        KafkaIngestor: "latest" only starts consuming from the moment a
        fresh consumer group's rebalance finalizes, not from subscribe()
        time, which can silently skip messages produced during that
        brief window. Default to "earliest" so no backlog is ever
        silently dropped.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        poll_timeout_ms: int = 1000,
        auto_offset_reset: str = "earliest",
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._group_id = group_id
        self._poll_timeout_ms = poll_timeout_ms
        self._auto_offset_reset = auto_offset_reset
        self._consumer = None
        self.last_poll_invalid_count: int = 0

    def start(self) -> None:
        if self._consumer is not None:
            return
        from confluent_kafka import Consumer

        self._consumer = Consumer({
            "bootstrap.servers": self._bootstrap_servers,
            "group.id": self._group_id,
            "auto.offset.reset": self._auto_offset_reset,
            "enable.auto.commit": True,
        })
        self._consumer.subscribe([self._topic])
        logger_obj.info(
            "[KafkaStreamReader] Subscribed to topic=%s group_id=%s",
            self._topic, self._group_id,
        )

    def stop(self) -> None:
        if self._consumer is not None:
            self._consumer.close()
            self._consumer = None
            logger_obj.info("[KafkaStreamReader] Consumer closed")

    def poll(self, timeout_ms: Optional[int] = None) -> List[MetricPoint]:
        if self._consumer is None:
            raise RuntimeError("[KafkaStreamReader] start() must be called before poll()")

        effective_timeout_s = (timeout_ms or self._poll_timeout_ms) / 1000.0
        points: List[MetricPoint] = []
        self.last_poll_invalid_count = 0

        msg = self._consumer.poll(timeout=effective_timeout_s)
        while msg is not None:
            if msg.error():
                logger_obj.warning("[KafkaStreamReader] Consumer error: %s", msg.error())
            else:
                point = self._parse(msg.value())
                if point is not None:
                    points.append(point)
                else:
                    self.last_poll_invalid_count += 1
            msg = self._consumer.poll(timeout=0)

        return points

    @staticmethod
    def _parse(raw_bytes: bytes) -> Optional[MetricPoint]:
        """Never raises — malformed messages are logged and skipped so a
        single bad point never crashes the worker."""
        try:
            payload = json.loads(raw_bytes)
        except json.JSONDecodeError as exc:
            logger_obj.warning("[KafkaStreamReader] Malformed JSON: %s", exc)
            return None

        missing = [f for f in REQUIRED_FIELDS if payload.get(f) is None]
        if missing:
            logger_obj.warning("[KafkaStreamReader] Missing field(s) %s in: %r", missing, payload)
            return None

        try:
            ts_raw = payload["timestamp"]
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            value = float(payload["value"])
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError(f"non-finite value: {value}")
        except (ValueError, TypeError) as exc:
            logger_obj.warning("[KafkaStreamReader] Invalid field value: %s", exc)
            return None

        return MetricPoint(
            vm_id=str(payload["vm_id"]),
            metric_name=str(payload["metric_name"]),
            timestamp=ts,
            value=value,
        )
