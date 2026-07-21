"""
phase2/ingestion/kinesis_ingestor.py
========================================
P2-M1  |  KinesisIngestor(BaseIngestor) — AWS Kinesis Data Streams adapter.

Same poll() -> List[RawRecord] contract as KafkaIngestor (LSP) — swap one
for the other via config with no changes anywhere else in the pipeline.
Requires `boto3`. Import deferred to __init__.
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


class KinesisIngestor(BaseIngestor):
    """
    Consumes cloud telemetry events from a single Kinesis shard.

    Parameters
    ----------
    stream_name:
        Kinesis stream name.
    shard_id:
        Shard to read from. Production deployments typically run one
        KinesisIngestor per shard.
    region_name:
        AWS region.
    poll_timeout_ms:
        Unused directly by Kinesis's GetRecords API (which is non-blocking),
        but kept for interface parity with BaseIngestor.poll().
    dead_letter_writer:
        Where schema-invalid events are routed. If None, only logged.
    """

    def __init__(
        self,
        stream_name: str,
        shard_id: str,
        region_name: str = "us-east-1",
        poll_timeout_ms: int = INGEST_POLL_MS,
        dead_letter_writer: Optional[DeadLetterWriter] = None,
    ) -> None:
        self._stream_name = stream_name
        self._shard_id = shard_id
        self._region_name = region_name
        self._poll_timeout_ms = poll_timeout_ms
        self._dlq_writer = dead_letter_writer
        self._client = None
        self._shard_iterator: Optional[str] = None
        self.last_poll_invalid_count: int = 0

    def start(self) -> None:
        if self._client is not None:
            return
        import boto3  # deferred import

        self._client = boto3.client("kinesis", region_name=self._region_name)
        resp = self._client.get_shard_iterator(
            StreamName=self._stream_name,
            ShardId=self._shard_id,
            ShardIteratorType="LATEST",
        )
        self._shard_iterator = resp["ShardIterator"]
        logger_obj.info(
            "[KinesisIngestor] Reading stream=%s shard=%s",
            self._stream_name, self._shard_id,
        )

    def stop(self) -> None:
        self._client = None
        self._shard_iterator = None
        logger_obj.info("[KinesisIngestor] Stopped")

    def poll(self, timeout_ms: Optional[int] = None) -> List[RawRecord]:
        if self._client is None or self._shard_iterator is None:
            raise RuntimeError("[KinesisIngestor] start() must be called before poll()")

        records: List[RawRecord] = []
        self.last_poll_invalid_count = 0
        resp = self._client.get_records(ShardIterator=self._shard_iterator, Limit=500)
        self._shard_iterator = resp.get("NextShardIterator")

        for kinesis_record in resp.get("Records", []):
            payload = None
            try:
                payload = json.loads(kinesis_record["Data"])
                records.append(SchemaValidator.validate(payload))
            except (json.JSONDecodeError, SchemaValidationError) as exc:
                self.last_poll_invalid_count += 1
                logger_obj.warning("[KinesisIngestor] Invalid record: %s", exc)
                if self._dlq_writer is not None:
                    self._dlq_writer.write(payload if payload is not None else {"raw": str(kinesis_record.get("Data"))}, str(exc))

        return records
