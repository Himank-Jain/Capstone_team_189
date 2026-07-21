"""
phase2/ingestion/pubsub_ingestor.py
=======================================
P2-M1  |  PubSubIngestor(BaseIngestor) — Google Cloud Pub/Sub adapter.

Same poll() -> List[RawRecord] contract as KafkaIngestor/KinesisIngestor
(LSP). Requires `google-cloud-pubsub`. Import deferred to __init__.
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


class PubSubIngestor(BaseIngestor):
    """
    Consumes cloud telemetry events via synchronous pull from a Google
    Cloud Pub/Sub subscription.

    Parameters
    ----------
    project_id:
        GCP project id.
    subscription_id:
        Pub/Sub subscription name (not the topic name).
    poll_timeout_ms:
        Max time to wait for at least one message per poll() call.
    dead_letter_writer:
        Where schema-invalid messages are routed. If None, only logged.
    """

    def __init__(
        self,
        project_id: str,
        subscription_id: str,
        poll_timeout_ms: int = INGEST_POLL_MS,
        dead_letter_writer: Optional[DeadLetterWriter] = None,
    ) -> None:
        self._project_id = project_id
        self._subscription_id = subscription_id
        self._poll_timeout_ms = poll_timeout_ms
        self._dlq_writer = dead_letter_writer
        self._subscriber = None
        self._subscription_path: Optional[str] = None
        self.last_poll_invalid_count: int = 0

    def start(self) -> None:
        if self._subscriber is not None:
            return
        from google.cloud import pubsub_v1  # deferred import

        self._subscriber = pubsub_v1.SubscriberClient()
        self._subscription_path = self._subscriber.subscription_path(
            self._project_id, self._subscription_id
        )
        logger_obj.info(
            "[PubSubIngestor] Pulling from subscription=%s", self._subscription_path
        )

    def stop(self) -> None:
        if self._subscriber is not None:
            self._subscriber.close()
            self._subscriber = None
            self._subscription_path = None
            logger_obj.info("[PubSubIngestor] Closed")

    def poll(self, timeout_ms: Optional[int] = None) -> List[RawRecord]:
        if self._subscriber is None:
            raise RuntimeError("[PubSubIngestor] start() must be called before poll()")

        effective_timeout_s = (timeout_ms or self._poll_timeout_ms) / 1000.0
        records: List[RawRecord] = []
        ack_ids: List[str] = []
        self.last_poll_invalid_count = 0

        response = self._subscriber.pull(
            request={
                "subscription": self._subscription_path,
                "max_messages": 500,
            },
            timeout=effective_timeout_s,
        )

        for received in response.received_messages:
            ack_ids.append(received.ack_id)
            payload = None
            try:
                payload = json.loads(received.message.data)
                records.append(SchemaValidator.validate(payload))
            except (json.JSONDecodeError, SchemaValidationError) as exc:
                self.last_poll_invalid_count += 1
                logger_obj.warning("[PubSubIngestor] Invalid message: %s", exc)
                if self._dlq_writer is not None:
                    self._dlq_writer.write(payload if payload is not None else {"raw": str(received.message.data)}, str(exc))

        if ack_ids:
            self._subscriber.acknowledge(
                request={"subscription": self._subscription_path, "ack_ids": ack_ids}
            )

        return records
