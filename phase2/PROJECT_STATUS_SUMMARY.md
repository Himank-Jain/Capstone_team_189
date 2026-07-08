# CAPSTONE-189 — Project Status Summary (Updated)

**Behavioral Anomaly Detection Platform — Multi-Cloud Entity Behavioral Intelligence**

---

## Part 1 — Phase 1 (P1-M1 → P1-M6): Now fully complete

| Module | Status | Notes |
|---|---|---|
| **P1-M1 — Historical Corpus** (`CorpusIterator`) | ✅ Complete | 41 passing unit tests. Unaffected by the schema redesign. |
| **P1-M2 — `StreamingAugPairsDataset`** | ✅ Complete (redesigned) | Event-based schema: `metric_name` as a 4th learned categorical embedding, single z-scored `value_norm`. Streams `aug_pairs.parquet` row-group by row-group. |
| **P1-M3 — `TstccEncoder`** | ✅ Complete, trained | `EmbeddingLayer → Time2Vec(k=8) → GRU(128, 2 layers) → AttentionPooling → ProjectionHead → L2-normalize`. Confirmed real vocab sizes: cloud=4, entity_type=21, namespace=21, metric_name=127 (incl. PAD/UNK). |
| **P1-M4 — `NTXentLossComputer` / `train_tstcc.py`** | ✅ Complete, trained | Symmetric NT-Xent loss + full training loop. `tstcc_encoder_final.pt` confirmed genuinely trained (see Part 4). |
| **P1-M5 — Behavioral Embedding Space** | ✅ Complete | Real code now in hand: `batch_encoder.py` (`BatchEncoder`, batches of 512, projection head disabled) + `faiss_indexer.py` (`build_faiss_index`, `FaissIndexer.add/search_topk/save/load`). Confirmed artifacts: `IndexIVFFlat`, 128-d, **280,305 vectors**, trained. |
| **P1-M6 — Model Registry / `ArtifactBundle`** | ✅ **Complete (just finished)** | Real `artifact_bundle.py` provided by teammate (`ArtifactBundle` dataclass, `.load()`, `.load_latest()`). The one missing piece — `phase1/registry/model_registry.py` (`ModelRegistry`, `ModelRegistryConfigData`) — was built to match the exact interface `artifact_bundle.py` already called, verified against the real `artifacts_manifest.json`. **Proven end-to-end**: `ArtifactBundle.load_latest()` correctly returns a live `TstccEncoder` (projection disabled) + `FaissIndexer` (280,305 vectors) from real files. |

**Real `shared/constants.py` now adopted** (previously reconstructed from docs) — confirms `TRAIN_LR` (1e-4 documented vs 3e-4 actual training run) and `TRAIN_TEMPERATURE` (0.07 documented vs 0.1 actual code) are **still open, unresolved discrepancies**, even in this fresh authoritative copy.

**Naming resolved:** `artifact_bundle.py`'s own docstring explicitly names its consumers as `InferenceEncoder` (P2-M3) and `ReferenceEncoderService` (P2-M4) — this superseded an earlier conflicting hint found in `tstcc_encoder.py`'s docstring (`InferenceEncoderSvc`/`ReferenceManager`), since `artifact_bundle.py` is the more current, authoritative source.

---

## Part 2 — Phase 2: P2-M1, P2-M2, P2-M3

### P2-M1 — Periodic Batch Ingestion ✅
`BaseIngestor` ABC, `KafkaIngestor` (tested against real Kafka), `KinesisIngestor`/`PubSubIngestor` (built, untested — need real cloud credentials), `BatchAccumulator`, `DeadLetterWriter`, `SchemaValidator`, `IngestionPipeline` (async orchestrator with health metrics).

### P2-M2 — Record Encoding ✅
`FeatureMetaStore`, `CategoricalEncoder`, `NumericalEncoder`, `ContextEncoder`, `RecordEncoder` — deliberately outputs raw indices/scalars only (never owns embedding logic), matching `TstccEncoder.forward()`'s exact contract.

### P2-M3 — Retrieved Encoder (Inference) ✅ **New this session**
`InferenceEncoder` — wraps a loaded `TstccEncoder` for production inference:
- Constructor **rejects** an encoder whose projection head is still enabled (safety check, not just a docstring warning)
- `encode()` — internally chunks at `chunk_size=64` to bound memory; chunking proven to produce results **identical** to one large batch
- `encode_single()` — proven to exactly match its corresponding row from a batched call
- `LatencyStats` — P50/P95/P99 tracking, bounded sample buffer
- CUDA warm-up on init (3 dummy batches, not counted in latency stats)

### Tests
**61 unit tests, all passing** (`tests/unit/phase2/`): schema validation (19), batch accumulation (10), record encoding (19), inference encoding (13).

---

## Part 3 — Phase 0: Adaptive Statistical Baseline (independent of Phase 1/2)

A lightweight, per-`(vm, metric)` rolling statistical anomaly detector — zero code dependency on `phase1/`, `phase2/`, or `shared/`. Fully built and verified this session:

| Component | Role |
|---|---|
| `BucketKeyResolver` | Timestamp → hour/weekday-weekend bucket, or global fallback |
| `WelfordAccumulator` | O(1) incremental mean/std, with a mathematically-proven `remove()` inverse for true sliding-window support |
| `RobustStatsAccumulator` | Median/MAD alternative for outlier-prone metrics |
| `ZScoreScorer` | Threshold-based anomaly flagging, cold-start suppression |
| `RollingBaselineStore` | Redis-backed, race-safe via `WATCH`/`MULTI`/`EXEC` with jittered backoff |
| `SeasonalityClassifier` | Per-metric bucketed-vs-global decision |
| `KafkaStreamReader` / `RedisStreamReader` | Self-contained ingestion adapters (separate from Phase 2's) |
| `AnomalyScoringWorker` | Orchestrates read → bucket → score → publish → update |

**45 unit tests, all passing**, plus:
- Real Redis via Docker: round-trip, eviction, and a **1,600-update / 32-thread stress test with zero lost writes** (after fixing a genuine concurrency bug — see Part 4)
- Full real Kafka → Redis E2E: 30 stable readings + 1 injected outlier, correctly flagged (`z=49.59`)
- **Real-data validation** against `pretrain_corpus.parquet` (57,600 real readings, one real month): 0.8% false-positive rate (sane for a 3σ threshold on real-world data), genuine diurnal pattern captured across buckets, injected 10× spike correctly caught (`z=339.82`)

**Honest caveat:** this corpus snapshot has **zero genuinely labeled anomalies** (`is_anomaly` is `False` for all 8,969,760 rows, confirmed) — likely the alert-anchor matching in `generate_corpus.py` found nothing for this snapshot. Worth flagging to whoever generated it; real precision/recall against ground truth isn't possible with this file.

---

## Part 4 — How we know it all actually works together

Every layer was verified against something real, with genuine bugs caught and fixed along the way — not just a clean-looking demo:

1. **Pandas `groupby`/`apply` bug** — silently dropped the `entity_id` column, causing 100% validation failures against real corpus data. Fixed to `.groupby("entity_id").head(200)`.
2. **Kafka consumer-group race condition** — `auto.offset.reset="latest"` skipped messages produced during a fresh consumer group's rebalance window. Fixed default to `"earliest"`.
3. **Producer false confidence** — original test script printed "Done." regardless of actual delivery outcome. Rewritten to track success/failure/timeout explicitly and exit non-zero on any failure.
4. **Real trained checkpoint, zero mismatch** — `tstcc_encoder_final.pt` loaded into an independently-built encoder with `strict=True`: **zero missing/unexpected keys**, embedding table shapes matched exactly (4/21/21/127).
5. **Redis WATCH-retry thundering herd** — under real OS-thread contention (not just `fakeredis`), 10 retries wasn't enough; some updates were silently dropped. Fixed with 100 retries + jittered exponential backoff, then proven correct at **1,600 concurrent updates, zero lost writes**.
6. **`FeatureMetaStore.from_dicts()` dict-unpacking bug** — `ArtifactBundle`'s `metric_value_stats` stores `{"mean":..., "std":...}` dicts, not tuples; naively unpacking a dict yields its *keys* as strings, causing a `float - str` crash. Fixed to normalize both formats.
7. **My own test-authoring bugs** (caught and fixed, not hidden): two Phase 2 worker tests called the wrong method and got wrong expectations; one Phase 0 percentile test had incorrect hand-computed math.

**Net result:** real Kafka → real validation/batching → real encoding → real trained neural network weights → real FAISS index, all proven to interoperate correctly, end to end, twice over (once for Phase 2, once independently for Phase 0).

---

## Open items still remaining

| Item | Status |
|---|---|
| `TRAIN_LR` (1e-4 vs 3e-4) | Still unresolved — needs a team decision + one-line constants fix |
| `TRAIN_TEMPERATURE` (0.07 vs 0.1) | Still unresolved — not tracked in docs, only surfaced via code inspection |
| **P2-M4 (`ReferenceEncoderService`)** | **Next up.** Needs a decision on injected-interface + stub approach, since P2-M6 (Dynamic Entity Store) and a historical-record source don't exist yet |
| `KinesisIngestor` / `PubSubIngestor` | Structurally complete, never live-tested (need real AWS/GCP credentials) |
| `generate_aug_pairs.py` / `vm_augmentation.py` | Legacy wide-schema versions, incompatible with the current pipeline; the real `aug_pairs.parquet` was produced by some other, unreleased version |
| Phase 0 real-anomaly validation | Blocked on this corpus snapshot having no labeled anomalies — would need a differently-generated corpus, or real production data, to check precision/recall properly |
