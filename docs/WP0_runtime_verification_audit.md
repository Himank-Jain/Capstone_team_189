# WP0 Runtime Verification Audit

Date: 2026-09-22
Package run: WP0 only (read-only audit)

## 1. Baseline and regression gate

The required Git baseline could not be created. `C:\Users\Himank\Desktop\Capstone\Capstone_final` is not a Git repository (`git status` and `git tag` both returned `fatal: not a git repository`). No tag, branch, or commit was created.

The full existing test suite was executed before this report was written. Collection stopped with 6 errors and 0 executed tests because the selected interpreter lacks `redis` and `fakeredis`:

- `tests/integration/phase2/test_entity_store_real_redis.py`: missing `redis`
- `tests/unit/phase0/test_anomaly_scoring_worker.py`: missing `fakeredis`
- `tests/unit/phase0/test_rolling_baseline_store.py`: missing `fakeredis`
- `tests/unit/phase2/test_alerting.py`: missing `fakeredis`
- `tests/unit/phase2/test_async_drift_worker.py`: missing `fakeredis`
- `tests/unit/phase2/test_entity_store.py`: missing `fakeredis`

This is an environment/checkout blocker, not a WP0 code failure. The demo smoke was run separately: `pytest tests/test_demo_api_app.py -q` passed 5 tests with 4 existing datetime deprecation warnings. Importing `backend.api_demo_ext.app` succeeded and registered the expected demo routes.

Because WP0 made no code changes, there is no after-test delta. The full-suite regression gate is **OPEN / not measurable** until the project is run from a Git checkout with the declared test dependencies installed.

## 2. Claims C1-C8

### C1: No autonomous runtime composition

**CONFIRMED.** `IngestionPipeline` is a reusable poll/accumulate controller in [phase2/ingestion/ingestion_pipeline.py](../phase2/ingestion/ingestion_pipeline.py#L20-L75), while the production-facing alert API is a standalone receiver of an already-built `AlertPayloadModel` in [phase2/alerting/api/alert_api.py](../phase2/alerting/api/alert_api.py#L43-L47). Repository search found no non-demo caller that composes ingestion, encoding, entity state, scoring, alert construction, and notification dispatch. The demo is the only assembled flow in [backend/api_demo_ext/app.py](../backend/api_demo_ext/app.py#L704-L817).

### C2: `live_ingestion` is not importable

**CONFIRMED.** No `live_ingestion/` package exists in the workspace. The provider files import `live_ingestion.connectors.base_live_ingestor` and `live_ingestion.mappers.vocab_reconciler`, for example [aws_live_ingestor.py](../aws_live_ingestor.py#L15-L19). Those imports cannot resolve from the current tree.

### C3: Live connector contract mismatch

**CONFIRMED.** [base_live_ingestor.py](../base_live_ingestor.py#L43-L83) defines `poll()` without a timeout argument and has no concrete `start()` or `stop()` implementation. [phase2/ingestion/base_ingestor.py](../phase2/ingestion/base_ingestor.py#L20-L55) requires `start()`, `stop()`, and `poll(timeout_ms: int) -> List[RawRecord]`; [phase2/ingestion/ingestion_pipeline.py](../phase2/ingestion/ingestion_pipeline.py#L65-L91) calls exactly that contract. A wrapper adapter is required; connector internals should remain frozen.

### C4: Notification persistence is in-memory

**PARTIAL.** [phase3/notifications/notification_dispatcher.py](../phase3/notifications/notification_dispatcher.py#L47-L78) provides an in-memory endpoint repository and delivery recorder, and [notification_dispatcher.py](../phase3/notifications/notification_dispatcher.py#L80-L111) provides in-memory idempotency. A Redis idempotency implementation exists at [notification_dispatcher.py](../phase3/notifications/notification_dispatcher.py#L113-L128), but there is no durable endpoint repository, policy repository, delivery repository, or provisioning service. The claim is therefore true for endpoint/policy/delivery configuration and false for idempotency as an absolute statement.

### C5: Alert API has no automatic upstream caller

**CONFIRMED.** `POST /alert` accepts `AlertPayloadModel` directly at [phase2/alerting/api/alert_api.py](../phase2/alerting/api/alert_api.py#L113-L127). The API does not consume `EventBatch`, invoke encoding, score an entity, or build the payload. Repository search found tests and the demo builder, but no non-demo runtime worker calling this endpoint or its dispatcher.

### C6: Compose contains infrastructure only

**CONFIRMED.** [docker-compose.yml](../docker-compose.yml#L1-L43) defines Zookeeper, Kafka, and Redis only. It has no runtime worker, alert API, notification service, Postgres/PGVector service, or aggregate health service.

### C7: unresolved imports

**CONFIRMED with required/optional classification.** The current interpreter's import scan reported `live_ingestion`, `azure`, `oci`, `psycopg`, `pgvector`, `pymongo`, and `psutil` unresolved. Their usage is:

| Import | Classification | Evidence and reason |
|---|---|---|
| `live_ingestion` | **REQUIRED for live mode; currently missing package** | Imported by all four provider entrypoints, e.g. [aws_live_ingestor.py](../aws_live_ingestor.py#L15-L19). |
| `azure` | **OPTIONAL provider dependency** | Used lazily by [azure_live_ingestor.py](../azure_live_ingestor.py#L31-L35); required only for Azure live ingestion. |
| `oci` | **OPTIONAL provider dependency** | Used lazily by [oci_live_ingestor.py](../oci_live_ingestor.py#L30-L35); required only for OCI live ingestion. |
| `psycopg` / `pgvector` | **OPTIONAL production storage dependency** | Used by [phase2/store/pgvector_entity_store.py](../phase2/store/pgvector_entity_store.py#L45-L52); required only when the PGVector store is selected. |
| `pymongo` | **OPTIONAL/offline corpus dependency** | Used by [scripts/generate_corpus.py](../scripts/generate_corpus.py#L30-L38), not the hot runtime path. |
| `psutil` | **OPTIONAL legacy training dependency** | Used by [phase1/legacy/generate_aug_pairs.py](../phase1/legacy/generate_aug_pairs.py#L40-L49); phase1 is frozen and out of scope. |

The declared [requirements.txt](../requirements.txt#L1-L21) also does not declare the Azure, OCI, psycopg/pgvector, pymongo, or psutil packages as optional extras.

### C8: no non-demo end-to-end test

**CONFIRMED.** The available integration tests cover phase-2 storage and phase-3 notification/API slices, but repository search found no `tests/e2e/` suite and no non-demo test asserting source-to-notification behavior through a runtime composition root.

## 3. Runtime wiring map as built

| Stage | Actual class / constructor | Input -> output | Who calls it today |
|---|---|---|---|
| Source ingestion | `KafkaIngestor(bootstrap_servers, topic, group_id, ...)`; analogous `KinesisIngestor` and `PubSubIngestor` | broker message -> `List[RawRecord]` | Unit tests/scripts only; `IngestionPipeline` accepts it but no production composition root instantiates the pipeline. |
| Live source | `BaseLiveIngestor(LiveIngestorConfigData)` plus provider subclasses | provider events -> `List[RawRecord]` | No caller; imports are broken because `live_ingestion/` is absent. |
| Batch | `BatchAccumulator(window_seconds, source)` | `RawRecord` -> `EventBatch` | `IngestionPipeline.start_async()` calls `add()` and `flush()`; no runtime caller starts it. |
| Ingestion controller | `IngestionPipeline(ingestor, on_batch, window_seconds, poll_timeout_ms, source_label)` | source poll -> callback with `EventBatch` | No non-demo caller found. |
| Record encoding | `RecordEncoder(feature_meta, seq_len)` | `List[RawRecord]` per entity -> tensor dict (`numeric`, `categorical`, `timestamps`, plus lengths in the batch path) | Demo constructs `RecordEncoder` but encodes its synthetic records inline; no live runtime caller found. |
| Model inference | `InferenceEncoder(encoder, chunk_size, device, warm_up)` | raw tensors -> `(N, 128)` embeddings | Tests only; requires an already-loaded `TstccEncoder`. |
| Entity aggregation | `CurrentEmbeddingAggregator()` / `aggregate_embeddings(...)` | IDs + embeddings -> `List[CurrentEmbedding]` | Tests only; no runtime caller found. |
| Entity state | `EntityStoreReader(redis_client_sync, redis_client_async, history_len_int)` and `EntityStoreWriter(redis_client_sync, history_len_int)` | Redis keys -> `EntityProfile`; current embedding/profile -> Redis | Unit/integration tests and scripts only. |
| Deviation | `CosineDeviationScorer(global_threshold, local_threshold)` / `compute_scores(current_emb, profile)` | current embedding + profile -> `DeviationResult` | Tests and demo-equivalent logic only. |
| Drift | `MmdDriftMonitor(entity_store_reader, ...)`; `AsyncDriftWorker(drift_monitor, redis_client_sync, ...)` | entity history -> `DriftScore` / cached future result | Tests and scripts only. |
| Similar episodes | `EpisodeRetriever(faiss_indexer, redis_client, cache_ttl_sec)` / `search(query_embedding, k, exclude_entity_id)` | embedding -> episode results | Tests only; requires a loaded FAISS index. |
| Final score | `AnomalyScorer()` / `score(ScoringInput)` | scalar component scores -> `AnomalyResult` | Tests and demo logic only. |
| Deduplication | `AlertDeduplicator(redis_client, ...)` / `check(anomaly_result)` | anomaly -> `DedupResult` | Tests and demo only. |
| Correlation | `CorrelationEngine(entity_attributes_provider, ...)` / `process(entity_id, canonical_incident_id, alert_ts)` | entity + incident -> `CorrelationResult` | Demo and tests only. |
| Escalation | `EscalationEngine(entity_metadata_provider, rules_path, ...)` / `process(...)` | anomaly + correlation metadata -> `EscalationResult` | Demo and tests only. |
| Alert assembly | `build_alert_payload(...)` | anomaly + escalation + correlation + episodes -> `AlertPayloadModel` | Demo and tests only. |
| Alert API | `create_app(notifiers, ..., notification_dispatcher)`; `POST /alert` | prebuilt payload -> dispatch response | Standalone default app and tests; no upstream runtime caller. |
| Phase-3 notification | `NotificationDispatcher(notifiers, endpoints, repositories...)` / `dispatch(payload, policy)` | payload + explicit policy -> delivery results | Integration/unit tests and optional injected AlertApi path; no durable tenant configuration. |

## 4. Adjacent-stage interface mismatches

1. **Live ingestion -> P2-M1 ingestion:** `BaseLiveIngestor.poll()` has no `timeout_ms`, `start()`, or `stop()` while `BaseIngestor` requires all three. This is the direct WP1 adapter boundary.
2. **RecordEncoder -> InferenceEncoder:** `RecordEncoder.encode_entity_records()` returns a dictionary for one entity, while `InferenceEncoder.encode()` accepts separate batched tensors and an optional lengths tensor. A runtime batching adapter must group/window records and stack dictionary values.
3. **InferenceEncoder -> CurrentEmbeddingAggregator:** embeddings are compatible, but the aggregator separately requires positional `entity_ids`, cloud-provider metadata, and a batch timestamp. The runtime must preserve this metadata while batching model outputs.
4. **Aggregator -> entity store:** `CurrentEmbedding` is the right write input, but no existing controller performs the required read-profile, EMA/reference update, current write, and profile write sequence.
5. **Detection components -> AnomalyScorer:** `CosineDeviationScorer`, drift, and episode retrieval return separate result types; `AnomalyScorer` only accepts scalar `ScoringInput`. A composition adapter must reduce the results and apply documented cold-start values.
6. **Async drift -> scoring:** `AsyncDriftWorker.submit_compute()` returns a `Future`, while `AnomalyScorer.score()` is synchronous. The runtime must use cached drift when present and define the non-blocking first-run fallback.
7. **FAISS episode retrieval -> production artifacts:** `EpisodeRetriever` requires an already-loaded `FaissIndexer`; the known incomplete P1-M5 artifact path means production mode cannot silently construct or fake this dependency.
8. **Alert API -> tenant notification:** the API receives a payload without a tenant field in the frozen `AlertPayloadModel`; its current fallback creates a `NotificationPolicy` for `default`, while the phase-3 dispatcher has only an ad hoc entity-to-tenant mapping. There is no `EntityTenantReader` or policy repository.
9. **Phase-3 endpoint -> notifier:** endpoint records carry `target`, but `_deliver_endpoint()` calls the channel notifier with only the payload. The endpoint target is not passed through the notifier contract, and `_channel_map()` selects one notifier per channel. Multiple tenant endpoints per channel therefore need an explicit adapter/design decision before production use.
10. **Durability boundary:** endpoint repository, delivery recorder, and policy resolution are memory-backed or absent, so restart durability and client onboarding are not currently represented by a runtime interface.

## 5. Recommended package order and risk

| Order | Package | Risk | Basis |
|---|---|---|---|
| 1 | WP1: live ingestion packaging + contract adapter | **Medium** | Narrow boundary fix; required before any live-source runtime can import or satisfy P2-M1. Must preserve frozen connector internals. |
| 2 | WP2: runtime composition root | **High** | Largest integration surface and depends on artifact availability, store contracts, async drift behavior, and alert/tenant seams. Requires plan approval and a new top-level package. |
| 3 | WP3: durable notification configuration | **High** | Needed for real onboarding and restart safety; requires a separate Postgres schema and explicit P3-M2 scope confirmation. |
| 4 | WP5: non-demo end-to-end test | **Medium** | Should validate WP1-WP3 together using offline fakes; it will expose remaining composition mismatches without live credentials. |
| 5 | WP4: runtime containers and health checks | **Medium** | Deployment should follow the verified composition root and durable service contracts; doing it earlier would package an unverified runtime. |

Recommended next package: **WP1**, after restoring a Git checkout and installing the baseline test dependencies so its regression gate is meaningful.

## 6. Required report checklist

- Files created/modified: this report only, [docs/WP0_runtime_verification_audit.md](WP0_runtime_verification_audit.md).
- Pre-existing source files edited: none.
- Updated `__init__.py` files: none.
- `shared/types.py` delta: none.
- `shared/constants.py` delta: none.
- Frozen-file diff: **PASS for this WP0 run**; no source files were edited.
- Defaults preserve behavior: **PASS for this WP0 run**; no runtime code changed.
- Lazy imports: **PARTIAL / OPEN**; provider SDKs are mostly lazy, but the missing `live_ingestion` package prevents imports.
- No hardcoded targets: **OPEN**; existing demo-only defaults are outside WP0 changes, and phase-3 endpoint target propagation remains unresolved.
- No new IAM permissions: **PASS**; no IAM files changed.
- Windows-safe: **PASS for this WP0 run**; no worker/process code changed. Future runtime work must continue to avoid unpicklable handles under spawn.
- Git baseline tag: **OPEN / blocked by non-Git checkout**.
- Full-suite regression: **OPEN / blocked at collection by missing `redis` and `fakeredis`**.
- Demo startup/routes: **PASS**; import smoke succeeded and 5 demo tests passed.

## 7. Repo-vs-planning discrepancies and open questions

1. The planning claim that live connectors are a drop-in replacement is false as built: the package is absent and the method contract differs from `BaseIngestor`.
2. The planning scope names a `NotificationPolicyRepository`, `NotificationProvisioningService`, and `EntityTenantReader`, but none exists in the current phase-3 tree.
3. The planning claim that `ArtifactBundle.load()` is the source of inference artifacts is not currently verifiable from a complete runtime path; `InferenceEncoder` requires an injected, already-loaded model and `EpisodeRetriever` requires an injected FAISS index.
4. `config/config.json` contains model metadata only; it does not provide a tenant registry, source registry, notification endpoint registry, or runtime service configuration.
5. The repository is not a Git checkout at the workspace path, so branch/commit/tag requirements cannot be satisfied here without the correct repository root.
6. Before WP2, the team must approve the new top-level runtime package location and decide whether the initial runtime may operate with the documented dev cold-start path when FAISS/artifacts are unavailable.

## 8. WP0 disposition

WP0 is complete as a read-only audit. No implementation package was run. The next action is to restore the Git/test baseline and then request approval to run WP1.