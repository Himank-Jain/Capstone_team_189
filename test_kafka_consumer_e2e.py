"""
test_kafka_consumer_e2e.py
============================
Full end-to-end version of the Kafka consumer test: real Kafka broker ->
SchemaValidator -> BatchAccumulator -> RecordEncoder -> the REAL trained
TstccEncoder (loaded from model_registry/tstcc_encoder_final.pt, sized
from config/feature_meta.json — the real P1-M6 registry artifact, not
recomputed vocab).

Run test_kafka_producer.py in a second terminal after this one prints
"[KafkaIngestor] Subscribed..." to see it process live events into real
128-d trained embeddings.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)

import torch

from phase1.models.tstcc_encoder import build_tstcc_encoder_for_aug_pairs
from phase2.encoding.feature_meta import FeatureMetaStore
from phase2.encoding.record_encoder import RecordEncoder
from phase2.ingestion.dead_letter_writer import DeadLetterWriter
from phase2.ingestion.ingestion_pipeline import IngestionPipeline
from phase2.ingestion.kafka_ingestor import KafkaIngestor

TOPIC = "telemetry-events"
GROUP_ID = "capstone-test-consumer-e2e-v1"  # bump this if you want a fresh re-read

FEATURE_META_PATH = "config/feature_meta.json"
ENCODER_WEIGHTS_PATH = "model_registry/tstcc_encoder_final.pt"

# ── 1. Load the REAL registry artifact and REAL trained encoder, once ───────
logger.info("Loading feature_meta.json from %s ...", FEATURE_META_PATH)
feature_meta = FeatureMetaStore.from_registry_json(FEATURE_META_PATH)

logger.info("Building TstccEncoder sized to real vocab...")
encoder = build_tstcc_encoder_for_aug_pairs(
    cloud_vocab_size_int=len(feature_meta.vocab_maps_dict["cloud"]),
    entity_type_vocab_size_int=len(feature_meta.vocab_maps_dict["entity_type"]),
    namespace_vocab_size_int=len(feature_meta.vocab_maps_dict["namespace"]),
    metric_name_vocab_size_int=len(feature_meta.vocab_maps_dict["metric_name"]),
    use_projection_bool=True,
)

logger.info("Loading real trained weights from %s ...", ENCODER_WEIGHTS_PATH)
ckpt = torch.load(ENCODER_WEIGHTS_PATH, map_location="cpu", weights_only=False)
missing, unexpected = encoder.load_state_dict(ckpt["state_dict"], strict=True)
assert not missing and not unexpected, f"Checkpoint mismatch! missing={missing} unexpected={unexpected}"
encoder.disable_projection()  # inference mode, per TstccEncoder's own docstring
encoder.eval()
logger.info("Encoder loaded and verified — strict load succeeded, projection head disabled.")

record_encoder = RecordEncoder(feature_meta, seq_len=32)

# ── 2. Wire up the real ingestion pipeline ───────────────────────────────────
dlq_writer = DeadLetterWriter(dlq_path="dead_letter_queue_e2e.jsonl")
ingestor = KafkaIngestor(
    bootstrap_servers="localhost:9092",
    topic=TOPIC,
    group_id=GROUP_ID,
    dead_letter_writer=dlq_writer,
)

def on_batch(batch):
    """Called every time BatchAccumulator flushes — this is where a real
    P2-M2 -> P2-M3 handoff would happen in the full system."""
    print(f"\n>>> FLUSHED BATCH: {len(batch.records)} valid, {batch.n_invalid} invalid")
    if not batch.records:
        return

    encoded_by_entity = record_encoder.encode_event_batch(batch)
    entity_ids, numeric_t, categorical_t, timestamps_t, lengths_t = (
        RecordEncoder.collate_encoded_batch(encoded_by_entity)
    )

    with torch.no_grad():
        embeddings = encoder(numeric_t, categorical_t, timestamps_t, lengths_t)

    print(f"    encoded {len(entity_ids)} entities -> embeddings {tuple(embeddings.shape)}")
    for i, eid in enumerate(entity_ids):
        norm = embeddings[i].norm(p=2).item()
        print(f"    {eid}: ||emb||={norm:.4f}  emb[:5]={[round(x,3) for x in embeddings[i,:5].tolist()]}")

    oov = record_encoder._categorical_encoder.oov_counts
    if any(oov.values()):
        print(f"    ⚠ OOV categorical lookups this batch: {oov}")

pipeline = IngestionPipeline(
    ingestor=ingestor,
    on_batch=on_batch,
    window_seconds=5,
    poll_timeout_ms=1000,
    source_label="kafka",
)

async def run_for_a_while():
    task = asyncio.create_task(pipeline.start_async())
    await asyncio.sleep(15)
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