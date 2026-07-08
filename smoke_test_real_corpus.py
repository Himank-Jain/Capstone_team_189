"""
Smoke test #2: same P2-M1 -> P2-M2 -> TstccEncoder chain, but using REAL
vocab/stats computed from pretrain_corpus.parquet and REAL sampled rows
for a couple of real entities, instead of synthetic toy data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import torch

from phase1.data.streaming_aug_pairs_dataset import (
    compute_vocab_sizes,
    compute_metric_value_stats,
)
from phase1.models.tstcc_encoder import build_tstcc_encoder_for_aug_pairs
from phase2.encoding.feature_meta import FeatureMetaStore
from phase2.encoding.record_encoder import RecordEncoder
from phase2.ingestion.batch_accumulator import BatchAccumulator
from phase2.ingestion.schema_validator import SchemaValidator, SchemaValidationError

CORPUS_PATH = "pretrain_corpus.parquet"

# ── 1. Real vocab / stats (same as your last command) ───────────────────────
print("Computing real vocab + stats from corpus (this may take a bit)...")
vocab_maps = compute_vocab_sizes(CORPUS_PATH)
metric_value_stats = compute_metric_value_stats(CORPUS_PATH)
feature_meta = FeatureMetaStore.from_dicts(vocab_maps, metric_value_stats)

# ── 2. Build a real-sized TstccEncoder ───────────────────────────────────────
encoder = build_tstcc_encoder_for_aug_pairs(
    cloud_vocab_size_int=len(vocab_maps["cloud"]),
    entity_type_vocab_size_int=len(vocab_maps["entity_type"]),
    namespace_vocab_size_int=len(vocab_maps["namespace"]),
    metric_name_vocab_size_int=len(vocab_maps["metric_name"]),
    use_projection_bool=True,
)
encoder.eval()
n_params = sum(p.numel() for p in encoder.parameters())
print(f"Encoder built: {n_params:,} parameters (real vocab sizes)")

# ── 3. Sample real rows for a couple of real entities ────────────────────────
df = pd.read_parquet(CORPUS_PATH, columns=[
    "entity_id", "timestamp", "cloud", "entity_type", "namespace",
    "metric_name", "value",
])
sample_entities = df["entity_id"].unique()[:3]
print(f"Sampling entities: {list(sample_entities)}")

subset = df[df["entity_id"].isin(sample_entities)]
# Cap to keep this fast — 200 rows per entity is plenty for a smoke test
subset = subset.groupby("entity_id").head(200)

# ── 4. Push through SchemaValidator -> BatchAccumulator, exactly like a live feed ──
accumulator = BatchAccumulator(window_seconds=9999, source="real_corpus_smoke_test")
n_invalid = 0
for row in subset.to_dict(orient="records"):
    try:
        accumulator.add(SchemaValidator.validate(row))
    except SchemaValidationError as exc:
        n_invalid += 1
accumulator.mark_invalid(n_invalid)

batch = accumulator.flush()
print(f"EventBatch: {len(batch.records)} valid, {batch.n_invalid} invalid")

# ── 5. Encode + feed into the real encoder ──────────────────────────────────
record_encoder = RecordEncoder(feature_meta, seq_len=32)
encoded_by_entity = record_encoder.encode_event_batch(batch)
print(f"Entities encoded: {list(encoded_by_entity.keys())}")

entity_ids, numeric_t, categorical_t, timestamps_t, lengths_t = (
    RecordEncoder.collate_encoded_batch(encoded_by_entity)
)
print(f"numeric_t={tuple(numeric_t.shape)}  categorical_t={tuple(categorical_t.shape)}  "
      f"lengths_t={lengths_t.tolist()}")

with torch.no_grad():
    embeddings = encoder(numeric_t, categorical_t, timestamps_t, lengths_t)

print(f"embeddings shape={tuple(embeddings.shape)}")
norms = embeddings.norm(p=2, dim=-1)
assert torch.allclose(norms, torch.ones_like(norms), atol=1e-4), norms

print(f"\nOOV categorical lookups: {record_encoder._categorical_encoder.oov_counts}")
print(f"OOV metric_name fallbacks: {record_encoder._numerical_encoder.oov_metric_count}")
print("\n✓ Real-corpus smoke test PASSED.")