"""
phase2/ingestion/kafka_ingestor.py
======================================
P2-M1  |  KafkaIngestor(BaseIngestor) — confluent-kafka consumer wrapper.

Requires the `confluent-kafka` package. Import is deferred inside
__init__ so the rest of the ingestion package (and its unit tests) don't
hard-fail on machines without a Kafka client installed.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from phase2.ingestion.base_ingestor import BaseIngestor
from phase2.ingestion.dead_letter_writer import DeadLetterWriter
from phase2.ingestion.schema_validator import SchemaValidationError, SchemaValidator
from shared.constants import INGEST_POLL_MS
from shared.types import RawRecord

logger_obj = logging.getLogger(__name__)


class KafkaIngestor(BaseIngestor):
    """
    Consumes cloud telemetry events from a Kafka topic.

    Parameters
    ----------
    bootstrap_servers:
        Kafka broker address(es), comma-separated.
    topic:
        Topic to subscribe to.
    group_id:
        Consumer group id. MUST be unique per independent consumer in a
        shared test cluster to avoid offset conflicts between teammates.
    poll_timeout_ms:
        Default poll timeout if not overridden per-call.
    dead_letter_writer:
        Where schema-invalid events are routed (DIP — injected, not
        constructed internally). If None, invalid events are only logged.
    auto_offset_reset:
        "earliest" (default) or "latest". "latest" only starts consuming
        from the moment this consumer group's partition assignment
        finalizes — NOT from when subscribe()/start() was called — which
        can silently skip messages produced during the brief rebalance
        window right after a fresh consumer group joins. "earliest" reads
        from the start of the topic for any partition this group has no
        committed offset for, which is almost always what you want for a
        batch-ingestion pipeline that must not silently drop backlog.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        poll_timeout_ms: int = INGEST_POLL_MS,
        dead_letter_writer: Optional[DeadLetterWriter] = None,
        auto_offset_reset: str = "earliest",
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._group_id = group_id
        self._poll_timeout_ms = poll_timeout_ms
        self._dlq_writer = dead_letter_writer
        self._auto_offset_reset = auto_offset_reset
        self._consumer = None  # lazily constructed in start()
        self.last_poll_invalid_count: int = 0

    def start(self) -> None:
        if self._consumer is not None:
            return  # already started — idempotent
        from confluent_kafka import Consumer  # deferred import

        self._consumer = Consumer({
            "bootstrap.servers": self._bootstrap_servers,
            "group.id": self._group_id,
            "auto.offset.reset": self._auto_offset_reset,
            "enable.auto.commit": True,
        })
        self._consumer.subscribe([self._topic])
        logger_obj.info(
            "[KafkaIngestor] Subscribed to topic=%s group_id=%s",
            self._topic, self._group_id,
        )

    def stop(self) -> None:
        if self._consumer is not None:
            self._consumer.close()
            self._consumer = None
            logger_obj.info("[KafkaIngestor] Consumer closed")

    def poll(self, timeout_ms: Optional[int] = None) -> List[RawRecord]:
        """
        Poll for available messages and return validated RawRecords.

        Malformed JSON or schema-invalid messages are logged and skipped
        here (best-effort parsing); IngestionPipeline is still responsible
        for routing any records it separately deems invalid to the DLQ —
        this method's own skips are a defensive fallback, not the primary
        validation path.
        """
        if self._consumer is None:
            raise RuntimeError("[KafkaIngestor] start() must be called before poll()")

        effective_timeout_s = (timeout_ms or self._poll_timeout_ms) / 1000.0
        records: List[RawRecord] = []
        self.last_poll_invalid_count = 0

        msg = self._consumer.poll(timeout=effective_timeout_s)
        while msg is not None:
            if msg.error():
                logger_obj.warning("[KafkaIngestor] Consumer error: %s", msg.error())
            else:
                payload = None
                try:
                    payload = json.loads(msg.value())
                    records.append(SchemaValidator.validate(payload))
                except (json.JSONDecodeError, SchemaValidationError) as exc:
                    self.last_poll_invalid_count += 1
                    logger_obj.warning("[KafkaIngestor] Invalid event: %s", exc)
                    if self._dlq_writer is not None:
                        self._dlq_writer.write(payload if payload is not None else {"raw": str(msg.value())}, str(exc))
            msg = self._consumer.poll(timeout=0)  # drain without re-blocking

        return records