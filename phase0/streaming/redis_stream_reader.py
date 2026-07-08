"""
phase0/streaming/redis_stream_reader.py
===========================================
Phase 0 · RedisStreamReader(BaseStreamReader) — alternative backend using
Redis Streams (XREAD) directly, for teams that want to avoid standing up
Kafka just for this lightweight layer. Same MetricPoint wire format and
LSP contract as KafkaStreamReader.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from phase0.streaming.base_stream_reader import BaseStreamReader
from phase0.streaming.kafka_stream_reader import REQUIRED_FIELDS
from phase0.types import MetricPoint

logger_obj = logging.getLogger(__name__)


class RedisStreamReader(BaseStreamReader):
    """
    Parameters
    ----------
    redis_client:
        Any redis-py-compatible client.
    stream_name:
        Redis Stream key to read from.
    consumer_group / consumer_name:
        Redis Streams consumer-group semantics (XREADGROUP) — allows
        multiple parallel readers to each get a disjoint slice of the
        stream, analogous to Kafka consumer groups/partitions.
    """

    def __init__(
        self,
        redis_client,
        stream_name: str,
        consumer_group: str,
        consumer_name: str,
        poll_timeout_ms: int = 1000,
    ) -> None:
        self._redis = redis_client
        self._stream_name = stream_name
        self._consumer_group = consumer_group
        self._consumer_name = consumer_name
        self._poll_timeout_ms = poll_timeout_ms
        self._started = False
        self.last_poll_invalid_count: int = 0

    def start(self) -> None:
        if self._started:
            return
        try:
            self._redis.xgroup_create(self._stream_name, self._consumer_group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):  # group already exists — fine, idempotent
                raise
        self._started = True
        logger_obj.info(
            "[RedisStreamReader] Reading stream=%s group=%s consumer=%s",
            self._stream_name, self._consumer_group, self._consumer_name,
        )

    def stop(self) -> None:
        self._started = False
        logger_obj.info("[RedisStreamReader] Stopped")

    def poll(self, timeout_ms: Optional[int] = None) -> List[MetricPoint]:
        if not self._started:
            raise RuntimeError("[RedisStreamReader] start() must be called before poll()")

        effective_timeout_ms = timeout_ms or self._poll_timeout_ms
        self.last_poll_invalid_count = 0
        points: List[MetricPoint] = []

        response = self._redis.xreadgroup(
            groupname=self._consumer_group,
            consumername=self._consumer_name,
            streams={self._stream_name: ">"},
            count=500,
            block=effective_timeout_ms,
        )
        if not response:
            return points

        for _stream_key, messages in response:
            for message_id, fields in messages:
                point = self._parse(fields)
                if point is not None:
                    points.append(point)
                else:
                    self.last_poll_invalid_count += 1
                self._redis.xack(self._stream_name, self._consumer_group, message_id)

        return points

    @staticmethod
    def _parse(fields: dict) -> Optional[MetricPoint]:
        """`fields` is the Redis Stream entry's field dict (str keys/values,
        or a nested JSON payload under a single 'data' field — support
        both shapes for flexibility)."""
        try:
            payload = json.loads(fields["data"]) if "data" in fields else fields
        except (json.JSONDecodeError, KeyError) as exc:
            logger_obj.warning("[RedisStreamReader] Malformed entry: %s", exc)
            return None

        missing = [f for f in REQUIRED_FIELDS if payload.get(f) is None]
        if missing:
            logger_obj.warning("[RedisStreamReader] Missing field(s) %s in: %r", missing, payload)
            return None

        try:
            ts = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            value = float(payload["value"])
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError(f"non-finite value: {value}")
        except (ValueError, TypeError) as exc:
            logger_obj.warning("[RedisStreamReader] Invalid field value: %s", exc)
            return None

        return MetricPoint(
            vm_id=str(payload["vm_id"]),
            metric_name=str(payload["metric_name"]),
            timestamp=ts,
            value=value,
        )
