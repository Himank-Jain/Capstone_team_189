"""
Smoke test: prove P2-M1/P2-M2 output plugs directly into the real,
uploaded TstccEncoder.forward() with no shape/dtype mismatches.
"""
import sys
from datetime import datetime, timedelta, timezone
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch

from phase2.encoding.feature_meta import FeatureMetaStore
from phase2.encoding.record_encoder import RecordEncoder
from phase2.ingestion.batch_accumulator import BatchAccumulator
from phase2.ingestion.schema_validator import SchemaValidator, SchemaValidationError
from shared.types import RawRecord
from phase1.models.tstcc_encoder import build_tstcc_encoder_for_aug_pairs

# ── 1. Simulate a tiny "training-time" vocab/stats (as if computed by
#      compute_vocab_sizes()/compute_metric_value_stats()) ──────────────────
vocab_maps = {
    "cloud": {"AWS": 1, "Azure": 2},
    "entity_type": {"VirtualMachine": 1, "StorageAccount": 2},
    "namespace": {"Compute": 1, "Storage": 2},
    "metric_name": {"cpu_usage": 1, "Availability": 2, "memory_usage": 3},
}
metric_value_stats = {
    "cpu_usage": (45.0, 20.0),
    "Availability": (99.5, 0.8),
    "memory_usage": (60.0, 15.0),
}
feature_meta = FeatureMetaStore.from_dicts(vocab_maps, metric_value_stats)

# ── 2. Build the REAL TstccEncoder sized to this vocab (mirrors train_tstcc.py) ──
encoder = build_tstcc_encoder_for_aug_pairs(
    cloud_vocab_size_int=len(vocab_maps["cloud"]),
    entity_type_vocab_size_int=len(vocab_maps["entity_type"]),
    namespace_vocab_size_int=len(vocab_maps["namespace"]),
    metric_name_vocab_size_int=len(vocab_maps["metric_name"]),
    use_projection_bool=True,
)
encoder.eval()

# ── 3. Simulate raw wire events -> SchemaValidator -> RawRecord ──────────────
now = datetime.now(timezone.utc)
raw_events = []
for i in range(10):
    raw_events.append({
        "entity_id": "vm-001",
        "timestamp": (now + timedelta(minutes=i)).isoformat(),
        "cloud": "AWS",
        "entity_type": "VirtualMachine",
        "namespace": "Compute",
        "metric_name": "cpu_usage" if i % 2 == 0 else "memory_usage",
        "value": 40.0 + i,
    })
# One entity with fewer events (tests variable-length lengths_tensor path)
for i in range(4):
    raw_events.append({
        "entity_id": "storage-002",
        "timestamp": (now + timedelta(minutes=i)).isoformat(),
        "cloud": "Azure",
        "entity_type": "StorageAccount",
        "namespace": "Storage",
        "metric_name": "Availability",
        "value": 99.0 + i * 0.1,
    })
# One deliberately malformed event (missing 'value') -> must be rejected, not crash
raw_events.append({
    "entity_id": "bad-003", "timestamp": now.isoformat(), "cloud": "AWS",
    "entity_type": "VirtualMachine", "namespace": "Compute", "metric_name": "cpu_usage",
})
# One event with a metric_name/cloud never seen in training -> OOV path
raw_events.append({
    "entity_id": "vm-001", "timestamp": (now + timedelta(minutes=99)).isoformat(),
    "cloud": "GCP", "entity_type": "VirtualMachine", "namespace": "Compute",
    "metric_name": "brand_new_metric", "value": 7.0,
})

accumulator = BatchAccumulator(window_seconds=9999, source="smoke_test")
n_invalid = 0
for raw in raw_events:
    try:
        accumulator.add(SchemaValidator.validate(raw))
    except SchemaValidationError as exc:
        n_invalid += 1
        print(f"  [DLQ] rejected malformed event: {exc}")
accumulator.mark_invalid(n_invalid)

batch = accumulator.flush()
assert batch is not None
print(f"EventBatch: {len(batch.records)} valid records, {batch.n_invalid} invalid")

# ── 4. RecordEncoder: RawRecord -> raw tensors matching TstccEncoder's contract ──
record_encoder = RecordEncoder(feature_meta, seq_len=32)
encoded_by_entity = record_encoder.encode_event_batch(batch)
print(f"Entities encoded: {list(encoded_by_entity.keys())}")

entity_ids, numeric_t, categorical_t, timestamps_t, lengths_t = (
    RecordEncoder.collate_encoded_batch(encoded_by_entity)
)
print(f"numeric_t={tuple(numeric_t.shape)}  categorical_t={tuple(categorical_t.shape)}  "
      f"timestamps_t={tuple(timestamps_t.shape)}  lengths_t={lengths_t.tolist()}")

assert numeric_t.shape[-1] == 3
assert categorical_t.shape[-1] == 4
assert timestamps_t.shape[-1] == 1
assert categorical_t.dtype == torch.int64
assert numeric_t.dtype == torch.float32

# ── 5. Feed DIRECTLY into the real, uploaded TstccEncoder — no adapter code ──
with torch.no_grad():
    embeddings = encoder(numeric_t, categorical_t, timestamps_t, lengths_t)

print(f"embeddings shape={tuple(embeddings.shape)}")
assert embeddings.shape == (len(entity_ids), 128)

# Confirm L2-normalisation contract holds
norms = embeddings.norm(p=2, dim=-1)
assert torch.allclose(norms, torch.ones_like(norms), atol=1e-4), norms

print("\n✓ ALL CHECKS PASSED — P2-M1 -> P2-M2 -> TstccEncoder.forward() is wire-compatible.")
print(f"✓ OOV categorical lookups handled gracefully: {record_encoder._categorical_encoder.oov_counts}")
print(f"✓ OOV metric_name z-score fallbacks: {record_encoder._numerical_encoder.oov_metric_count}")
