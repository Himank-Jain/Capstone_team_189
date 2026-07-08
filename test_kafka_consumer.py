"""
test_kafka_consumer.py
=======================
Runs the REAL KafkaIngestor + IngestionPipeline against the local broker
and topic populated by test_kafka_producer.py. Proves:
  - KafkaIngestor.poll() actually pulls messages off a real broker
  - Malformed events route to DeadLetterWriter (real file, not just logged)
  - BatchAccumulator correctly buffers valid records
  - IngestionPipeline's health counters track total/invalid events

Uses a short window_seconds so the demo finishes in a few seconds rather
than waiting for the real INGEST_BATCH_WIN_SEC=300s default.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

from phase2.ingestion.dead_letter_writer import DeadLetterWriter
from phase2.ingestion.ingestion_pipeline import IngestionPipeline
from phase2.ingestion.kafka_ingestor import KafkaIngestor

TOPIC = "telemetry-events"
GROUP_ID = "capstone-test-consumer-v1"  # bump the suffix if you re-run and want fresh offsets

dlq_path = "dead_letter_queue_kafka_test.jsonl"
dlq_writer = DeadLetterWriter(dlq_path=dlq_path)

ingestor = KafkaIngestor(
    bootstrap_servers="localhost:9092",
    topic=TOPIC,
    group_id=GROUP_ID,
    dead_letter_writer=dlq_writer,
)

received_batches = []

def on_batch(batch):
    print(f"\n>>> FLUSHED BATCH: {len(batch.records)} valid records, "
          f"{batch.n_invalid} invalid, source={batch.source}")
    for rec in batch.records:
        print(f"    {rec.entity_id}  {rec.metric_name}={rec.value}")
    received_batches.append(batch)

pipeline = IngestionPipeline(
    ingestor=ingestor,
    on_batch=on_batch,
    window_seconds=5,          # short window for this demo
    poll_timeout_ms=1000,
    source_label="kafka",
)

async def run_for_a_while():
    task = asyncio.create_task(pipeline.start_async())
    await asyncio.sleep(15)     # run long enough for a couple of flush cycles
    pipeline.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

asyncio.run(run_for_a_while())

print(f"\n--- Summary ---")
print(f"events_received_total: {pipeline.events_received_total}")
print(f"validation_errors_total: {pipeline.validation_errors_total}")
print(f"validation_error_rate: {pipeline.validation_error_rate:.3f}")
print(f"batches flushed: {len(received_batches)}")

print(f"\n--- DLQ file contents ({dlq_path}) ---")
if os.path.exists(dlq_path):
    with open(dlq_path, "r", encoding="utf-8") as fh:
        print(fh.read())
else:
    print("(no DLQ file created — no invalid events were routed)")