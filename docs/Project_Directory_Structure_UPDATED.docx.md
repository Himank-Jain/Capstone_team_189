**CAPSTONE PROJECT · TEAM 189**

**Project Directory Structure**

*Nomenclature System · SOLID & GRASP Design Principles · LLM Context Primers*

*Behavioral Anomaly Detection Platform · 20 Modules · 2 Phases — the canonical reference for variable names, class names, file paths, and integration contracts.*

| Revision note This edition incorporates the Phase 1 Architecture Update Addendum (dated after initial Phase 1 encoder development). Updated sections are marked with an orange UPDATED tag. Sections 1.3–1.5 (Phase 2, shared/, config/tests/scripts), Section 3 (SOLID), Section 4 (GRASP), and Section 5 (shared/types.py) are unaffected and unchanged from the original. |
| :---- |

# **Contents**

* 1\. Project Directory Structure — annotated full tree

* 2\. Naming Conventions (Nomenclature System) — 2a Classes · 2b Functions & Methods · 2c Variables · 2d Constants · 2e Files, Packages & Git Branches

* 3\. SOLID Principles — applied per module

* 4\. GRASP Principles — applied per module

* 5\. Cross-Module Integration Contract (shared/types.py)

* 6\. LLM Context Primers — 6a Global Project Primer · 6b Per-Module Primers · 6c How to Use Primers in Prompts

# **1\. Project Directory Structure**

*Every path below is relative to the project root (capstone/). Module IDs in comments (e.g. \# P1-M1) map directly to the team planner. Keep each Python file named after its primary class in snake\_case.*

## **1.1  Root Layout**

| capstone/                                \# project root ├── phase1/                              \# Phase 1 \- Offline Pretraining (P1-M1 \-\> P1-M6) ├── phase2/                              \# Phase 2 \- Online Inference   (P2-M1 \-\> P2-M14) ├── shared/                              \# Inter-module contracts & utilities ├── config/                              \# All YAML / JSON configuration ├── tests/                               \# unit / integration / e2e test suites ├── notebooks/                           \# Jupyter exploration & monitoring ├── scripts/                             \# CLI entry-points ├── model\_registry/                      \# Local artifact store (gitignored data, not code) ├── docker-compose.yml                   \# Redis \- Kafka \- PostgreSQL local dev stack ├── requirements.txt                     \# Pinned Python dependencies ├── .env.example                         \# Template for environment variables ├── .gitignore └── README.md |
| :---- |

## **1.2  phase1/  —  Offline Pretraining**

  **UPDATED — Phase 1 Architecture Addendum**  

Supersedes the original tree below. This is the AS-BUILT structure validated during Phase 1 encoder development — see the Phase 1 Architecture Update Addendum, Section 3, for the full rationale.

| phase1/ ├── \_\_init\_\_.py │ ├── corpus/                              \# P1-M1  Historical Corpus  \[UNCHANGED \- 41 passing tests\] │   ├── \_\_init\_\_.py │   └── corpus\_iterator.py               \# class CorpusIterator, class SchemaValidator │ ├── data/                                \# P1-M2  Augmentation Pairs  \[NEW \- replaces corpus+pairs split\] │   └── streaming\_aug\_pairs\_dataset.py   \# StreamingAugPairsDataset, StreamingDatasetConfigData, │                                        \#   compute\_vocab\_sizes(), compute\_metric\_value\_stats(), │                                        \#   contrastive\_collate\_fn() │ ├── models/                              \# P1-M3  Contrastive Encoder (TSTCC)  \[CONSOLIDATED\] │   └── tstcc\_encoder.py                 \# TstccEncoder, EmbeddingLayer, Time2Vec, AttentionPooling, │                                        \#   ProjectionHead, CategoricalFieldConfigData, │                                        \#   EmbeddingLayerConfigData, TstccEncoderConfigData, │                                        \#   build\_tstcc\_encoder\_for\_aug\_pairs() │ ├── losses/                              \# P1-M4  Contrastive Loss  \[MOVED\] │   └── ntxent\_loss.py                   \# NTXentLossComputer, NTXentLossConfigData │ ├── train/                               \# P1-M4  Training Entry Point  \[MOVED\] │   └── train\_tstcc.py                   \# main() \- full training script (CLI entry point) │ └── (P1-M5, P1-M6 not yet started \- embedding\_space/, registry/ folders as originally planned) |
| :---- |
| **Why the flatter layout** The four encoder sub-components (Time2Vec, AttentionPooling, ProjectionHead, EmbeddingLayer) are small, always used together, and never imported independently anywhere else in the codebase — splitting them across four files added navigation overhead without a corresponding SRP benefit. If a future module needs one of them standalone, extract it back out at that point rather than pre-splitting speculatively. |
| **Superseded (original plan, no longer accurate)** phase1/encoder/tstcc\_encoder.py \+ time2vec.py \+ attention\_pooling.py \+ projection\_head.py (4 files) \-\> now phase1/models/tstcc\_encoder.py (1 file). phase1/augmentation/pair\_generator.py (+ base\_augmenter.py, temporal\_jitter.py, attribute\_masker.py) \-\> now phase1/data/streaming\_aug\_pairs\_dataset.py. phase1/training/nt\_xent\_loss.py \+ training\_loop.py \+ cosine\_lr\_scheduler.py \-\> now phase1/losses/ntxent\_loss.py \+ phase1/train/train\_tstcc.py (no standalone TrainingLoop or CosineLrScheduler classes). |

## **1.3  phase2/  —  Online Inference**

*Unchanged — not affected by the Phase 1 redesign.*

| phase2/ ├── \_\_init\_\_.py ├── ingestion/                           \# P2-M1  Periodic Batch Ingestion │   ├── \_\_init\_\_.py │   ├── base\_ingestor.py                 \# class BaseIngestor  (ABC) │   ├── kafka\_ingestor.py                \# class KafkaIngestor │   ├── kinesis\_ingestor.py               \# class KinesisIngestor │   ├── pubsub\_ingestor.py                \# class PubSubIngestor │   ├── batch\_accumulator.py              \# class BatchAccumulator │   └── dead\_letter\_writer.py             \# class DeadLetterWriter │ ├── encoding/                            \# P2-M2  Record Encoding │   ├── \_\_init\_\_.py │   ├── record\_encoder.py                 \# class RecordEncoder (assembles sub-encoders) │   ├── categorical\_encoder.py            \# class CategoricalEncoder │   ├── numerical\_encoder.py              \# class NumericalEncoder │   ├── context\_encoder.py                \# class ContextEncoder │   ├── inference\_encoder.py              \# class InferenceEncoder        \# P2-M3 │   └── reference\_encoder\_service.py      \# class ReferenceEncoderService \# P2-M4 │ ├── embedding/                            \# P2-M5  Current Embedding │   ├── \_\_init\_\_.py │   └── current\_embedding\_aggregator.py   \# class CurrentEmbeddingAggregator │ ├── store/                                \# P2-M6  Dynamic Entity Store │   ├── \_\_init\_\_.py │   ├── base\_entity\_store.py              \# class BaseEntityStore  (ABC) │   ├── entity\_store\_reader.py            \# class EntityStoreReader │   ├── entity\_store\_writer.py            \# class EntityStoreWriter │   ├── redis\_entity\_store.py             \# class RedisEntityStore │   └── pgvector\_entity\_store.py          \# class PgVectorEntityStore │ ├── detection/                            \# P2-M7 \-\> P2-M10  Detection Engine │   ├── \_\_init\_\_.py │   ├── cosine\_deviation\_scorer.py        \# class CosineDeviationScorer   \# P2-M7 │   ├── mmd\_drift\_monitor.py              \# class MmdDriftMonitor          \# P2-M8 │   ├── async\_drift\_worker.py             \# class AsyncDriftWorker         \# P2-M8 │   ├── episode\_retriever.py              \# class EpisodeRetriever         \# P2-M9 │   └── anomaly\_scorer.py                 \# class AnomalyScorer            \# P2-M10 │ └── alerting/                             \# P2-M11 \-\> P2-M14  Alert Pipeline     ├── \_\_init\_\_.py     ├── alert\_deduplicator.py             \# class AlertDeduplicator       \# P2-M11     ├── correlation\_engine.py             \# class CorrelationEngine        \# P2-M12     ├── escalation\_engine.py              \# class EscalationEngine         \# P2-M13     ├── alert\_api.py                      \# FastAPI app factory            \# P2-M14     └── notifiers/         ├── \_\_init\_\_.py         ├── base\_notifier.py              \# class BaseNotifier  (ABC)         ├── slack\_notifier.py             \# class SlackNotifier         ├── email\_notifier.py             \# class EmailNotifier         └── pagerduty\_notifier.py         \# class PagerDutyNotifier |
| :---- |

## **1.4  shared/  —  Cross-Module Contracts**

*Unchanged.*

| shared/ ├── \_\_init\_\_.py ├── types.py          \# ALL dataclasses shared across modules (the integration contract) ├── constants.py      \# UPPER\_SNAKE constants \- grouped by module prefix ├── config.py         \# ConfigLoader \- reads config/config.yaml on import ├── exceptions.py     \# Custom exception hierarchy └── logger.py         \# Structured logger factory \- get\_logger(module\_name) |
| :---- |

## **1.5  config/, tests/, scripts/, notebooks/**

*Unchanged.*

| config/ ├── config.yaml                \# Main hyperparams: embed\_dim, gru\_hidden, thresholds ├── escalation\_rules.yaml      \# Ordered IF-THEN escalation rules (P2-M13) └── feature\_meta.json          \# Vocabulary maps \+ scaler params \- version-locked to model tests/ ├── unit/ │   ├── phase1/                \# test\_corpus\_iterator.py, test\_nt\_xent\_loss.py ... │   └── phase2/                \# test\_cosine\_scorer.py, test\_deduplicator.py ... ├── integration/               \# test\_encoding\_pipeline.py, test\_entity\_store.py ... └── e2e/                       \# test\_full\_pipeline.py \- synthetic event \-\> alert scripts/ ├── train.py                   \# python scripts/train.py \--config config/config.yaml ├── run\_inference.py           \# python scripts/run\_inference.py \--env prod ├── build\_faiss\_index.py       \# python scripts/build\_faiss\_index.py \--corpus s3://... └── generate\_test\_data.py      \# Synthetic multi-cloud event generator for local tests notebooks/ ├── data\_exploration.ipynb     \# Schema analysis, distribution plots ├── training\_monitor.ipynb     \# Loss curves, embedding space UMAP visualization └── alert\_dashboard.ipynb      \# Historical alert analysis, score distributions |
| :---- |

# **2\. Naming Conventions (Nomenclature System)**

*These conventions are mandatory for all code in this project. Consistent naming lets any team member read any file without orientation time, and lets LLMs generate correct code from a short primer (Section 6). Follow PEP 8 as the baseline, then apply the project-specific rules below.*

## **2a.  Classes — PascalCase \+ Role Suffix**

  **UPDATED — Phase 1 Architecture Addendum**  

Every class name must end with a suffix that declares its role. This makes the type system human-readable: you never need to open a file to know what a class does.

| Suffix | Role / Pattern | SOLID / GRASP | Examples in this project |
| :---- | :---- | :---- | :---- |
| Base… | Abstract base class (ABC) — never instantiated | OCP · Interface Segregation | BaseLoader, BaseIngestor, BaseNotifier, BaseEntityStore |
| …Iterator | Yields items lazily on demand | SRP · Information Expert | CorpusIterator |
| …Loader | Reads data from a source and returns raw records | SRP | ParquetLoader, JsonLoader |
| …Validator | Checks data against a schema or constraint set | SRP · Protected Variations | SchemaValidator |
| …Dataset | PyTorch (Iterable)Dataset streaming a parquet source | SRP · Information Expert | StreamingAugPairsDataset (NEW — replaces Augmenter/Generator split for P1-M2) |
| …Encoder | Transforms one representation into another | SRP · DIP | TstccEncoder, RecordEncoder, CategoricalEncoder, InferenceEncoder |
| …Computer | Stateless computation object, deviates from the …Loss suffix originally planned | SRP | NTXentLossComputer (⚠ deviation — planned as NtXentLoss) |
| …ConfigData | Immutable dataclass carrying config for another class | Low Coupling | StreamingDatasetConfigData, CategoricalFieldConfigData, EmbeddingLayerConfigData, TstccEncoderConfigData, NTXentLossConfigData |
| …Indexer | Builds and queries a vector index | SRP · Information Expert | FaissIndexer |
| …Registry | Stores and retrieves versioned artifacts | Pure Fabrication | ModelRegistry |
| …Bundle | Immutable data container grouping related artifacts | Low Coupling | ArtifactBundle |
| …Ingestor | Consumes events from a specific stream source | LSP · OCP | KafkaIngestor, KinesisIngestor, PubSubIngestor |
| …Accumulator | Collects items until a flush condition is met | SRP · High Cohesion | BatchAccumulator |
| …Aggregator | Combines multiple inputs into a single output | SRP · Creator | CurrentEmbeddingAggregator |
| …Store | Persists and retrieves keyed state | DIP · Indirection | RedisEntityStore, PgVectorEntityStore |
| …Reader | Read-only interface over a store | ISP | EntityStoreReader |
| …Writer | Write-only interface over a store | ISP | EntityStoreWriter, DeadLetterWriter |
| …Scorer | Computes a numeric score from inputs | SRP · DIP | CosineDeviationScorer, AnomalyScorer |
| …Monitor | Continuously observes a metric or distribution | SRP · High Cohesion | MmdDriftMonitor |
| …Worker | Background async/threaded task executor | SRP | AsyncDriftWorker |
| …Retriever | Searches and returns matching records from a store | SRP · Information Expert | EpisodeRetriever |
| …Deduplicator | Suppresses repeated identical events | SRP · High Cohesion | AlertDeduplicator |
| …Engine | Orchestrates a multi-step logical process | Controller · High Cohesion | CorrelationEngine, EscalationEngine |
| …Service | Stateful long-running component with lifecycle | Controller · DIP | ReferenceEncoderService |
| …Notifier | Sends an alert through one specific channel | OCP · Polymorphism | SlackNotifier, EmailNotifier, PagerDutyNotifier |
| …Result | Immutable output dataclass from a scorer or engine | Low Coupling · Indirection | DeviationResult, DriftResult, AnomalyResult, DedupResult, CorrelationResult, EscalationResult |
| …Input | Typed input dataclass passed into a scorer | Low Coupling | ScoringInput, EncoderInput |
| …Batch | A time-windowed collection of events | Low Coupling | EventBatch |
|  |  |  |  |

**Superseded / removed from Section 2a**

PairGenerator (…Generator) — the P1-M2 role is now filled by StreamingAugPairsDataset (…Dataset suffix); no static pair-file generation step exists anymore.

NtXentLoss, TrainingLoop, CosineLrScheduler — no longer exist as standalone classes. NT-Xent is implemented as NTXentLossComputer; the training loop and LR scheduling are inlined into train\_tstcc.py's main() using torch.optim.lr\_scheduler.CosineAnnealingLR directly.

## **2b.  Functions & Methods — snake\_case \+ Action Prefix**

  **UPDATED — Phase 1 Architecture Addendum**  

The first word of every function name must be a verb that describes the action. This makes call sites self-documenting.

| Prefix | Meaning | When to use | Examples |
| :---- | :---- | :---- | :---- |
| compute\_ | Pure mathematical operation — no side effects | Scores, distances, statistics | compute\_cosine\_distance(), compute\_mmd\_score(), compute\_centroid\_ema(), compute\_vocab\_sizes() (NEW), compute\_metric\_value\_stats() (NEW) |
| build\_ | Constructs an in-memory structure from inputs | Indices, graphs, tensors, factories | build\_faiss\_index(), build\_entity\_graph(), build\_pair\_batch(), build\_tstcc\_encoder\_for\_aug\_pairs() (NEW) |
| encode\_ | Transforms one representation into another | All encoding steps | encode\_record(), encode\_categorical(), encode\_timestamp() |
| load\_ | Reads an artifact from disk / remote storage | Models, indices, configs | load\_weights(), load\_vocabulary(), load\_faiss\_index() |
| save\_ | Persists an artifact to disk / remote storage | Checkpoints, indices | save\_checkpoint(), save\_faiss\_index(), save\_artifact\_bundle() |
| fetch\_ | Reads live data from an external system | Redis, Kafka, DB reads | fetch\_entity\_history(), fetch\_centroid(), fetch\_batch() |
| write\_ | Pushes data to an external store | Redis, DB, DLQ writes | write\_current\_emb(), write\_centroid(), write\_dead\_letter() |
| update\_ | Modifies existing state in-place or in-store | EMA updates, counters | update\_centroid\_ema(), update\_history\_buf(), update\_stats() |
| validate\_ | Checks a contract; raises on failure | Schema, shape, range checks | validate\_schema(), validate\_emb\_shape(), validate\_timestamp() |
| normalize\_ | Transforms data to a canonical form | Timestamp, embedding norms | normalize\_timestamp(), normalize\_emb\_l2(), normalize\_score() |
| aggregate\_ | Combines multiple items into one | Embedding aggregation | aggregate\_embeddings(), aggregate\_batch\_events() |
| detect\_ | Runs a detection algorithm and returns a result | Drift, anomaly detection | detect\_drift(), detect\_anomaly(), detect\_community() |
| retrieve\_ | Queries a store / index and returns matches | FAISS search, entity lookup | retrieve\_similar\_episodes(), retrieve\_entity\_profile() |
| dispatch\_ | Routes an output to one or more destinations | Alert delivery | dispatch\_alert(), dispatch\_to\_slack(), dispatch\_to\_pagerduty() |
| register\_ | Adds an entry to a registry or tracking structure | Model registry, incidents | register\_artifact(), register\_incident() |
| is\_ | Boolean predicate — always returns bool | State / condition checks | is\_duplicate(), is\_business\_hours(), is\_cold\_start() |
| has\_ | Boolean existence / presence check | Null guards | has\_valid\_centroid(), has\_history(), has\_drift\_score() |
| get\_ | Simple property getter — never modifies state | Property access | get\_centroid(), get\_history(), get\_latest\_version() |
| to\_ | Type / format conversion | Tensor, JSON, numpy casts | to\_tensor(), to\_numpy(), to\_json(), to\_float16() |
|  |  |  |  |

**New functions from the redesign (P1-M2 / P1-M3)**

**compute\_vocab\_sizes()** — single full-file pass building label→index maps for all 4 categorical columns (cloud, entity\_type, namespace, metric\_name).

**compute\_metric\_value\_stats()** — single full-file pass computing per-metric\_name (mean, std) for z-scoring.

**build\_tstcc\_encoder\_for\_aug\_pairs()** — factory wiring vocab sizes into a fully-configured TstccEncoder.

**contrastive\_collate\_fn()** — standard PyTorch collate function batching (seq\_a, seq\_b) pairs into stacked tensors for the DataLoader.

## 

## **2c.  Variables — snake\_case \+ Type Suffix**

*Unchanged.*

Variable names encode both meaning and type. The suffix tells you what kind of object it is; the prefix tells you what it represents. Never use single-letter names outside loop indices.

| Suffix | Type represented | Rule | Examples |
| :---- | :---- | :---- | :---- |
| \_emb | numpy ndarray / Tensor — embedding vector | Shape must be (..., 128\) — always L2-normalised | current\_emb, centroid\_emb, ref\_emb, query\_emb |
| \_tensor | PyTorch Tensor (any shape) | Use \_emb when shape is (\*, 128); \_tensor otherwise | input\_tensor, output\_tensor, mask\_tensor |
| \_score | float in \[0, 1\] | All scores are bounded; assert 0 ≤ x ≤ 1 | deviation\_score, drift\_score, similarity\_score, final\_score |
| \_batch | EventBatch or list of records | Do not call a single record a \_batch | event\_batch, record\_batch, emb\_batch |
| \_id | str identifier (single) | Always a string, never an int | entity\_id, incident\_id, alert\_id, group\_id |
| \_ids | List\[str\] — collection of ids | Use the plural suffix | entity\_ids, related\_ids, incident\_ids |
| \_ts | datetime / ISO-8601 string (timestamp) | Always UTC; use datetime with tzinfo=UTC | batch\_ts, last\_update\_ts, first\_seen\_ts |
| \_path | pathlib.Path or str file path | Prefer pathlib.Path over raw str | encoder\_path, index\_path, config\_path |
| \_cfg | dict / dataclass — config section | Load from config.yaml; never hardcode values | encoder\_cfg, redis\_cfg, faiss\_cfg |
| \_dim | int — dimensionality | Name the specific dimension | embed\_dim, hidden\_dim, proj\_dim |
| \_map | dict — key→value mapping | Vocabulary, index mappings | vocab\_map, entity\_map, episode\_meta\_map |
| \_buf | list / deque — transient in-memory buffer | For accumulator / ring-buffer patterns | event\_buf, history\_buf |
| \_flag | bool — a binary signal or alert trigger | Distinct from is\_ methods — flags are stored state | drift\_flag, dedup\_flag, cold\_start\_flag, global\_flag |
| \_threshold | float — configurable cutoff value | Always loaded from config, never hardcoded | global\_threshold, drift\_threshold, sev\_crit\_threshold |
| \_ttl | int — time-to-live in seconds | Use \_ttl for Redis TTL parameters | cache\_ttl, dedup\_ttl, drift\_cache\_ttl |
| n\_ | int — a count / cardinality | Use as prefix, not suffix | n\_entities, n\_episodes, n\_layers, n\_negatives |
| k\_ | int — a top-K or k-nearest param | Use as prefix, not suffix | k\_episodes, k\_neighbors, k\_time2vec |

## **2d.  Constants — UPPER\_SNAKE\_CASE \+ Module Prefix (shared/constants.py)**

  **UPDATED — Phase 1 Architecture Addendum**  

All constants live in shared/constants.py. Use module prefixes so any constant is uniquely identifiable across the whole codebase.

| \# shared/constants.py  \--  complete constant registry \# \-- Encoder (P1-M3, P2-M3, P2-M4) \----------------------------- ENC\_EMBED\_DIM        \= 128    \# output embedding dimensionality      \[UNCHANGED\] ENC\_FEATURE\_DIM      \= 256    \# concatenated input feature width     \[UNCHANGED\] ENC\_GRU\_HIDDEN       \= 128    \# GRU hidden state size                \[UNCHANGED\] ENC\_GRU\_N\_LAYERS     \= 2      \# stacked GRU depth                    \[UNCHANGED\] ENC\_TIME2VEC\_K       \= 8      \# number of Time2Vec sine terms        \[UNCHANGED\] ENC\_PROJ\_DIM         \= 128    \# projection head output dim           \[UNCHANGED\] ENC\_DROPOUT          \= 0.1                                          \# \[UNCHANGED\] \# \-- Augmentation Pairs / Encoder Input (P1-M2, P1-M3)  \[NEW SECTION\] \-- AUG\_PAIRS\_NUMERIC\_COLS      \= \['value\_norm', 'hour\_of\_day', 'day\_of\_week'\]  \# was 14 cols AUG\_PAIRS\_NUM\_NUMERIC       \= 3        \# was 14 AUG\_PAIRS\_CATEGORICAL\_COLS  \= \['cloud', 'entity\_type', 'namespace', 'metric\_name'\]  \# was 3 AUG\_VALUE\_NORM\_EPS          \= 1e-6     \# floors per-metric std to avoid divide-by-zero \# AUG\_PAIRS\_METRIC\_COLS / AUG\_PAIRS\_MASK\_COLS \-- REMOVED (no fixed metric list; \#   metric\_name is now a learned categorical embedding, not hardcoded wide columns) \# metric\_name vocab size is data-dependent \-- computed via compute\_vocab\_sizes() \#   (127 classes in current corpus sample; do not hardcode) \# \-- Training (P1-M4) \------------------------------------------- TRAIN\_TEMPERATURE    \= 0.07   \# NT-Xent temperature (tau)            \[UNCHANGED\] TRAIN\_LR             \= 1e-4   \# AdamW learning rate   \[SEE OPEN ITEM BELOW\] TRAIN\_WEIGHT\_DECAY   \= 1e-4                                         \# \[UNCHANGED\] TRAIN\_GRAD\_CLIP\_NORM \= 1.0                                          \# \[UNCHANGED\] TRAIN\_BATCH\_SIZE     \= 256                                          \# \[UNCHANGED\] \# \-- FAISS (P1-M5, P2-M9) \---------------------------------------- FAISS\_N\_LIST         \= 100    \# IVF cluster count FAISS\_N\_PROBE        \= 20     \# clusters searched per query FAISS\_TOP\_K          \= 10     \# k nearest episodes returned \# \-- Ingestion (P2-M1) \-------------------------------------------- INGEST\_BATCH\_WIN\_SEC \= 300    \# 5-minute batch window INGEST\_POLL\_MS       \= 100    \# Kafka poll timeout \# \-- Entity Store / Redis (P2-M6) \---------------------------------- REDIS\_HISTORY\_LEN    \= 30     \# rolling history window REDIS\_EMB\_BYTES      \= 256    \# 128 \* float16 REDIS\_DEDUP\_TTL      \= 300    \# dedup window TTL (seconds) REDIS\_DRIFT\_CACHE\_TTL= 1800   \# MMD cache TTL (seconds) \# \-- Detection Thresholds (P2-M7, P2-M8, P2-M10) \-------------------- SCORE\_W\_DEVIATION    \= 0.4    \# weight in final anomaly formula SCORE\_W\_DRIFT        \= 0.4 SCORE\_W\_SIMILARITY   \= 0.2 SCORE\_GLOBAL\_THRESH  \= 0.3    \# cosine deviation flag threshold SCORE\_LOCAL\_THRESH   \= 0.25 SCORE\_DRIFT\_THRESH   \= 0.5 SCORE\_SEV\_MEDIUM     \= 0.3    \# severity cutoffs SCORE\_SEV\_HIGH       \= 0.6 SCORE\_SEV\_CRITICAL   \= 0.8 \# \-- Reference encoder (P2-M4) \-------------------------------------- REF\_HISTORY\_DAYS     \= 90     \# past window for MMD baseline REF\_CENTROID\_ALPHA   \= 0.1    \# EMA update factor |
| :---- |
| **Open reconciliation item — TRAIN\_LR** TRAIN\_LR is documented as 1e-4 above (matches the original plan), but as of the addendum the running training job is using 3e-4. This is flagged, not yet resolved. Confirm with Member A whether 3e-4 was an intentional tune, then update this constant to match whichever is correct before P1-M5/P1-M6 begin. Do not silently pick one — the checkpoint and this file must agree. |

## **2e.  Files, Packages & Git Branches**

*Unchanged.*

| Artefact | Convention | Example |
| :---- | :---- | :---- |
| Python files | snake\_case — named after primary class | tstcc\_encoder.py → class TstccEncoder |
| Test files | test\_ prefix, mirrors source path | tests/unit/phase1/test\_nt\_xent\_loss.py |
| Config files | snake\_case YAML/JSON | escalation\_rules.yaml, feature\_meta.json |
| Git feature branches | feature/{module-id}-{short-name} | feature/P1-M3-tstcc-encoder |
| Git fix branches | fix/{module-id}-{issue-slug} | fix/P2-M6-redis-ltrim-race |
| Commit messages | type(scope): description | feat(P1-M3): add AttentionPooling layer |
| Notebook files | snake\_case, descriptive purpose | training\_monitor.ipynb |

# **3\. SOLID Principles — Applied Per Module**

*Unchanged from the original plan.*

*SOLID is a set of five design principles that keep code modular, testable, and easy to extend. Below, each principle is defined and then shown concretely in the project modules.*

## **S — Single Responsibility Principle (SRP)**

**Rule:** *Every class has exactly one reason to change.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| SchemaValidator (P1-M1) | Validates schema only. It does not load files (ParquetLoader does that) and does not deduplicate (CorpusIterator does that). |
| NTXentLossComputer (P1-M4) | Computes loss only. The optimizer step and LR schedule are inlined into train\_tstcc.py's main(), kept separate from loss computation. |
| AlertDeduplicator (P2-M11) | Deduplicates only. It does not compute scores (AnomalyScorer) and does not route alerts (AlertApi). |
| BaseNotifier subclasses (P2-M14) | SlackNotifier sends to Slack only. EmailNotifier sends email only. Adding PagerDuty never touches Slack code. |
| Anti-pattern to avoid | Avoid: a single class that loads data, validates it, augments it, AND trains the model. Split it. |

## **O — Open/Closed Principle (OCP)**

**Rule:** *Classes are open for extension, closed for modification.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| BaseIngestor (P2-M1) | Adding a new cloud stream (e.g. Azure Event Hub) \= new AzureEventHubIngestor subclass. BatchAccumulator and IngestionPipeline are never modified. |
| StreamingAugPairsDataset (P1-M2) | New augmentation strategies are assumed baked into aug\_pairs.parquet upstream; the dataset's windowing logic never needs to change to support them. |
| BaseNotifier (P2-M14) | New alert channel \= new subclass. AlertApi.dispatch() iterates over a list of notifiers — it never changes. |
| Anti-pattern to avoid | Anti-pattern: if/elif chain in BatchAccumulator checking the cloud provider type. Replace with a registry of ingestor subclasses. |

## **L — Liskov Substitution Principle (LSP)**

**Rule:** *Subtypes must be substitutable for their base type without breaking behaviour.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| KafkaIngestor / KinesisIngestor / PubSubIngestor | All return List\[Event\] from poll(). All accept the same constructor params (topic, config). BatchAccumulator only talks to BaseIngestor — swapping implementations never breaks it. |
| RedisEntityStore / PgVectorEntityStore | Both implement the same EntityStoreReader / EntityStoreWriter interfaces. Detection modules never know which backend is active. |
| SlackNotifier / EmailNotifier | Both implement dispatch(AlertPayload) → DispatchResult. AlertApi calls dispatch() identically on all notifiers. |
| Anti-pattern to avoid | Anti-pattern: KinesisIngestor.poll() returning a dict instead of List\[Event\]. That breaks LSP and crashes BatchAccumulator. |

## **I — Interface Segregation Principle (ISP)**

**Rule:** *Clients should not be forced to depend on methods they do not use.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| EntityStoreReader vs EntityStoreWriter (P2-M6) | CosineDeviationScorer only reads — it depends on EntityStoreReader alone. ReferenceEncoderService only writes — it depends on EntityStoreWriter alone. Neither is forced to implement both. |
| BaseLoader (P1-M1) | ParquetLoader and JsonLoader implement load() only. They are not forced to implement validate() — that is SchemaValidator's job. |
| Anti-pattern to avoid | Anti-pattern: a single IEntityStore interface with 20 methods that forces every consumer to implement write\_centroid() even if it never writes. |

## **D — Dependency Inversion Principle (DIP)**

**Rule:** *High-level modules depend on abstractions, not concrete implementations.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| AnomalyScorer (P2-M10) | Constructor accepts BaseDeviationScorer, BaseDriftMonitor, BaseEpisodeRetriever — not CosineDeviationScorer directly. Swap the implementation for testing without changing AnomalyScorer. |
| AlertApi (P2-M14) | Constructor accepts List\[BaseNotifier\] injected from outside. Alert logic does not know Slack exists. |
| IngestionPipeline (P2-M1) | Constructor accepts BaseIngestor. Pipeline is testable with a MockIngestor that returns canned events. |
| Config loading everywhere | All classes receive cfg: dict from ConfigLoader — never call yaml.safe\_load() inside a class. Tested by passing a test config dict. |
| Anti-pattern to avoid | Anti-pattern: AnomalyScorer importing CosineDeviationScorer at the top of the file and instantiating it internally. That makes it untestable and tightly coupled. |

# **4\. GRASP Principles — Applied Per Module**

*Unchanged from the original plan.*

*GRASP (General Responsibility Assignment Software Patterns) is a set of 9 patterns for deciding which class should own which behaviour. They complement SOLID by answering the question: 'Who should do this?'*

## **Information Expert**

**Rule:** *Assign responsibility to the class that has the information needed to fulfil it.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| EntityStore (P2-M6) | Owns centroid updates (update\_centroid\_ema) because it already holds all embeddings. |
| FaissIndexer (P1-M5) | Owns index search because it holds the FAISS index in memory. |
| ArtifactBundle (P1-M6) | Owns load() because it knows all file paths for the model artifacts. |

## **Creator**

**Rule:** *Assign class B the responsibility to create class A if B contains, records, or closely uses A.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| CurrentEmbeddingAggregator creates CurrentEmbedding | It has all the data: entity\_id, encoded embeddings, batch\_ts. |
| StreamingAugPairsDataset yields windowed pairs | It owns the windowing logic and has both matched views in scope (replaces PairGenerator's former Creator role). |
| AlertApi creates AlertPayload | It receives all sub-results and assembles the final delivery object. |

## **Controller**

**Rule:** *Assign the responsibility of receiving system events to a class that represents the overall system or use-case.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| AlertApi (P2-M14) | Handles all incoming alert events; orchestrates deduplication → correlation → escalation → dispatch. |
| train\_tstcc.py main() (P1-M4) | Controls the epoch cycle: load batch → forward → loss → backward → step → checkpoint. (Previously a standalone TrainingLoop class; now a CLI script function — the Controller role is unchanged.) |
| IngestionPipeline (P2-M1) | Controls the ingestion cycle: poll → validate → accumulate → flush. |

## **Low Coupling**

**Rule:** *Assign responsibilities so that unnecessary dependencies are avoided.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| shared/types.py as the only inter-module contract | Modules never import each other's internal classes. CosineDeviationScorer takes a DeviationInput dataclass — it never imports EntityStore. |
| Injected configs | No class imports yaml.safe\_load directly. Config dict is injected via constructor. |
| BaseNotifier list injection (P2-M14) | AlertApi does not import SlackNotifier. It accepts List\[BaseNotifier\] — never creates its dependencies. |

## **High Cohesion**

**Rule:** *Assign responsibilities so related things stay together and unrelated things stay apart.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| phase2/detection/ folder | CosineDeviationScorer, MmdDriftMonitor, EpisodeRetriever, AnomalyScorer all live together — they are all about producing a final score. |
| phase2/alerting/ folder | AlertDeduplicator, CorrelationEngine, EscalationEngine, AlertApi — all post-score alert handling. |
| shared/ folder | Only pure cross-cutting concerns (types, constants, config, logging). No business logic. |

## **Polymorphism**

**Rule:** *Assign responsibility using polymorphic operations for behaviour that varies by type.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| BaseAugmenter.apply() — historical note | Prior to the redesign, PairGenerator called apply() on any augmenter without knowing which one. Augmentation now happens upstream of phase1/, so this pattern is retained conceptually in how consumers of aug\_pairs.parquet remain agnostic to how jitter/masking were produced. |

## **Pure Fabrication**

**Rule:** *Assign responsibilities to artificial helper classes (not domain concepts) to maintain low coupling and high cohesion.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| ModelRegistry (P1-M6) | No real-world 'model registry' entity exists in the domain — it is a fabrication to manage artifact versioning cleanly without coupling Phase 1 output to Phase 2 input. |
| BatchAccumulator (P2-M1) | A fabricated helper — not a domain concept but needed to decouple polling from batch flushing. |
| AsyncDriftWorker (P2-M8) | Fabricated to isolate the async/threading concern from MmdDriftMonitor's pure detection logic. |

## **Indirection**

**Rule:** *Use an intermediary object to decouple two components and reduce direct coupling.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| shared/types.py | The central indirection layer. P2-M7 produces DeviationResult; P2-M10 consumes DeviationResult — neither knows about the other's internals. |
| ConfigLoader (shared/config.py) | All classes receive config through ConfigLoader — decoupled from file paths and YAML parsing details. |
| EntityStoreReader / Writer interfaces | Detection modules only see the reader interface. They are decoupled from whether Redis or PgVector is the backend. |

## **Protected Variations**

**Rule:** *Identify points of variation and create a stable interface around them.*

| Where in this project | How the principle is applied |
| :---- | :---- |
| Escalation rules in escalation\_rules.yaml | Business escalation logic changes often. Encapsulating it in YAML means EscalationEngine never changes when rules change. |
| Score thresholds in config.yaml | SCORE\_SEV\_CRITICAL\_THRESHOLD can be tuned without touching code. |
| BaseEntityStore abstraction | If Redis is replaced by DynamoDB, only a new DynamoEntityStore is added. No detection module changes. |

# **5\. Cross-Module Integration Contract (shared/types.py)**

| Good news — no changes required shared/types.py is UNCHANGED by the Phase 1 redesign. The redesign happened entirely inside the numeric\_features / categorical\_fields payload of RawRecord and the view\_1/view\_2 tensor contents of AugmentedPair — both dataclasses were already generic enough to absorb it. See the compatibility notes below the code block. |
| :---- |

*shared/types.py is the single source of truth for ALL dataclasses passed between modules. No module may import another module's internal classes directly. Every inter-module value must be wrapped in one of these dataclasses. Freeze this file in Week 1 — any change requires a team PR with migration notes.*

| \# shared/types.py \-- complete integration contract from dataclasses import dataclass, field from datetime import datetime from enum import Enum from typing import List, Optional import numpy as np \# \-- Enumerations \-------------------------------------------------- class Severity(str, Enum):     LOW \= 'LOW'; MEDIUM \= 'MEDIUM'; HIGH \= 'HIGH'; CRITICAL \= 'CRITICAL' class GroupType(str, Enum):     ISOLATED \= 'ISOLATED'; CORRELATED \= 'CORRELATED'; REGIONAL\_OUTAGE \= 'REGIONAL\_OUTAGE' class SevLevel(str, Enum):   \# Escalation severity     SEV1 \= 'SEV1'; SEV2 \= 'SEV2'; SEV3 \= 'SEV3'; SEV4 \= 'SEV4' class NotifyMethod(str, Enum):     PAGE \= 'PAGE'; SLACK \= 'SLACK'; EMAIL \= 'EMAIL' \# \-- Phase 1 / Shared Encoding \-------------------------------------- @dataclass class RawRecord:     entity\_id:          str     timestamp:          datetime        \# always UTC     op\_id:              str     region:              str     cloud\_provider:     str             \# AWS | Azure | GCP | OCI     numeric\_features:   List\[float\]     \# now 1 value\_norm reading per event row     categorical\_fields: dict            \# now includes 'metric\_name' in addition                                         \# to cloud/entity\_type/namespace @dataclass class AugmentedPair:     entity\_id:  str     view\_1:     np.ndarray             \# shape (seq\_len, feature\_dim) \- 256 at encoder boundary     view\_2:     np.ndarray     batch\_ts:   datetime \# \-- Phase 2 Ingestion \------------------------------------------------ @dataclass class EventBatch:     records:    List\[RawRecord\]     batch\_ts:   datetime     source:     str                    \# kafka | kinesis | pubsub     n\_invalid:  int \= 0                \# count of DLQ events \# \-- Embeddings \--------------------------------------------------------- @dataclass class CurrentEmbedding:     entity\_id:      str     emb:            np.ndarray         \# shape (128,) \- L2-normalised     batch\_ts:       datetime     n\_records:      int     cloud\_provider: str @dataclass class EntityProfile:     entity\_id:      str     centroid\_emb:   np.ndarray         \# shape (128,)     history\_embs:   List\[np.ndarray\]   \# up to REDIS\_HISTORY\_LEN entries     emb\_variance:   float     n\_records:      int     last\_update\_ts: datetime     cold\_start\_flag:bool \= False \# \-- Detection Results \------------------------------------------------- @dataclass class DeviationResult:     entity\_id:         str     global\_score:      float           \# \[0,1\]     local\_score:       float           \# \[0,1\]     global\_flag:       bool     local\_flag:        bool     batch\_ts:          datetime @dataclass class DriftResult:     entity\_id:    str     drift\_score:  float                \# \[0,1\]     drift\_flag:   bool     computed\_at:  datetime     is\_stale:     bool \= False @dataclass class EpisodeMatch:     similarity\_score:  float     episode\_id:        str     entity\_id:         str     timestamp:         datetime     cloud\_provider:    str     severity\_label:    Optional\[str\] @dataclass class SimilarityResult:     entity\_id:       str     mean\_similarity: float             \# \[0,1\]     episode\_matches: List\[EpisodeMatch\]     batch\_ts:        datetime @dataclass class ScoringInput:     entity\_id:        str     deviation\_result: DeviationResult     drift\_result:     DriftResult     similarity\_result:SimilarityResult     batch\_ts:         datetime @dataclass class AnomalyResult:     entity\_id:              str     final\_score:            float     severity:               Severity     deviation\_contribution: float     drift\_contribution:     float     similarity\_contribution:float     batch\_ts:               datetime \# \-- Alert Pipeline \------------------------------------------------------- @dataclass class DedupResult:     entity\_id:            str     is\_duplicate:         bool     canonical\_incident\_id: str     recurrence\_count:     int     first\_seen\_ts:        datetime @dataclass class CorrelationResult:     entity\_id:       str     incident\_group\_id: str     related\_ids:     List\[str\]     group\_size:      int     group\_type:      GroupType @dataclass class EscalationResult:     entity\_id:      str     sev\_level:      SevLevel     target\_team:    str     notify\_method:  NotifyMethod     policy\_applied: str @dataclass class AlertPayload:     alert\_id:               str        \# UUID4     entity\_id:              str     batch\_ts:               datetime     final\_score:            float     severity:               Severity     sev\_level:              SevLevel     deviation\_score:        float     drift\_score:            float     similarity\_score:       float     similar\_episodes:       List\[EpisodeMatch\]     related\_ids:            List\[str\]     group\_type:             GroupType     target\_team:            str     notify\_method:          NotifyMethod     cloud\_provider:         str     region:                 str |
| :---- |

## **Compatibility notes (Phase 1 redesign)**

| Dataclass | Field | Clarification |
| :---- | :---- | :---- |
| RawRecord | numeric\_features: List\[float\] | Now populated with a single value\_norm reading per event row, not 6 fixed metrics. Field type/name unchanged. |
| RawRecord | categorical\_fields: dict | Now includes a 'metric\_name' key in addition to cloud/entity\_type/namespace. Field type/name unchanged. |
| AugmentedPair | view\_1 / view\_2: np.ndarray, shape (seq\_len, feature\_dim) | feature\_dim is unchanged at the encoder boundary (still 256 after embedding+projection); only what is concatenated to reach it changed. |

# **6\. LLM Context Primers**

*A primer is a short, dense string prepended to any AI prompt for this project. It gives the LLM just enough context — module role, key types, key constants, conventions — to generate correctly-integrated code without you having to re-explain the whole system. Copy the relevant primer to the top of every AI prompt for this project.*

## **6a.  Global Project Primer**

*Unchanged.*

Use this at the top of any prompt that touches multiple modules or introduces a new concept.

| \[CAPSTONE-189\] Project: Behavioral Anomaly Detection for multi-cloud (AWS/Azure/GCP/OCI). 20 modules across 2 phases. Phase1=offline contrastive pretraining (TSTCC GRU encoder). Phase2=online inference; compare current\_emb vs entity baseline \-\> anomaly score \-\> alert. Lang: Python 3.10, PyTorch 2.x, FastAPI, Redis, FAISS, PostgreSQL+PGVector. Conventions: PascalCase+RoleSuffix classes, snake\_case+ActionPrefix funcs, snake\_case+TypeSuffix vars, UPPER\_SNAKE+ModulePrefix constants. Contracts: all inter-module values via shared/types.py dataclasses. SOLID+GRASP: SRP per class, DIP via constructor injection, ISP via Reader/Writer split. Embeddings: 128-d L2-norm float32. Redis history: float16. Config from config/config.yaml. Final score formula: 0.4\*deviation\_score \+ 0.4\*drift\_score \+ 0.2\*(1-similarity\_score). |
| :---- |

## **6b.  Per-Module Primers**

Append the relevant module primer AFTER the global primer. Together they give the LLM full context in under 10 lines.

### **P1-M1 — CorpusIterator**

*Unchanged.*

| \[P1-M1 CorpusIterator\] Loads Parquet+JSON minute-wise cloud telemetry. Returns batches of RawRecord. Validates via SchemaValidator. Deduplicates by (entity\_id, timestamp). Normalises timestamps to UTC datetime. Handles chunked reads for large files. Key classes: CorpusIterator, SchemaValidator, ParquetLoader(BaseLoader), JsonLoader(BaseLoader). |
| :---- |

### **P1-M2 — StreamingAugPairsDataset**

  **UPDATED — Phase 1 Architecture Addendum**  

*Replaces the P1-M2 PairGenerator primer. PairGenerator \+ static .npz pair files no longer exist.*

| \[P1-M2 StreamingAugPairsDataset\] PyTorch IterableDataset streaming aug\_pairs.parquet row-group by row-group (never loads full file). Each row \= ONE (timestamp, metric\_name, value) event, not a fixed-width timestep. Z-scores 'value' per metric\_name via precomputed GLOBAL stats (compute\_metric\_value\_stats()). Encodes cloud/entity\_type/namespace/metric\_name via GLOBAL vocab maps (compute\_vocab\_sizes()). Builds sliding windows of seq\_len consecutive EVENTS per entity across matched view='a'/'b' pairs. CRITICAL: never store an open pyarrow.parquet.ParquetFile as an \_\_init\_\_ instance attribute \-- open it lazily per-process, or DataLoader(num\_workers\>0) crashes on Windows (pickling TypeError). Key classes: StreamingAugPairsDataset, StreamingDatasetConfigData. Key fn: contrastive\_collate\_fn(). |
| :---- |

### **P1-M3 — TstccEncoder**

  **UPDATED — Phase 1 Architecture Addendum**  

*Input contract changed from 14 numeric \+ 3 categorical to 3 numeric \+ 4 categorical. Internal architecture is unchanged.*

| \[P1-M3 TstccEncoder\] PyTorch nn.Module. Input contract: 3 numeric (value\_norm, hour\_of\_day, day\_of\_week) \+ 4 categorical (cloud, entity\_type, namespace, metric\_name) \-\> concatenated to (batch, seq\_len, 256). Output: (batch, ENC\_EMBED\_DIM=128) L2-norm. Layers: EmbeddingLayer \-\> Time2Vec(k=ENC\_TIME2VEC\_K=8) \-\> GRU(hidden=128, layers=2) \-\> AttentionPooling \-\> ProjectionHead. save\_weights(path), load\_weights(path). Projection head stripped at inference. metric\_name\_vocab\_size\_int is a required 4th vocab arg to build\_tstcc\_encoder\_for\_aug\_pairs(), computed from the FULL file (cardinality varies by resource type). Key classes: TstccEncoder, Time2Vec, AttentionPooling, ProjectionHead, EmbeddingLayer, TstccEncoderConfigData. |
| :---- |

### **P1-M4 — NTXentLossComputer / train\_tstcc.py**

  **UPDATED — Phase 1 Architecture Addendum**  

*Class name deviates from the planned NtXentLoss. No standalone TrainingLoop or CosineLrScheduler class.*

| \[P1-M4 NTXentLossComputer\] NT-Xent contrastive loss. Inputs: z\_i, z\_j (batch,128) L2-norm. Tau=TRAIN\_TEMPERATURE=0.07. Temporal neg masking: same (entity\_id, session\_id) excluded from neg pool. train\_tstcc.py main(): AdamW lr=TRAIN\_LR (see Section 2d open item), CosineAnnealingLR (T\_max=20), grad\_clip\_norm=1.0, batch=256, checkpoint every 5 epochs \-\> model\_registry/. Key classes: NTXentLossComputer, NTXentLossConfigData. No standalone TrainingLoop/CosineLrScheduler \-- both inlined into train\_tstcc.py's main() using torch.optim.lr\_scheduler.CosineAnnealingLR directly. |
| :---- |

### **P1-M5 — FaissIndexer**

*Unchanged.*

| \[P1-M5 FaissIndexer\] Encodes all historical records via BatchEncoder(TstccEncoder). Builds FAISS IndexIVFFlat(nlist=100). Metadata tagged: entity\_id, timestamp, cloud\_provider, severity\_label. serialize/load via faiss.write\_index/read\_index. EmbeddingVisualiser: UMAP 2D optional. Key classes: BatchEncoder, FaissIndexer, EmbeddingVisualiser. |
| :---- |

### **P1-M6 — ModelRegistry / ArtifactBundle**

*Unchanged.*

| \[P1-M6 ModelRegistry\] ArtifactBundle(dataclass): version, encoder\_path, faiss\_index\_path, config, feature\_meta, training\_ts, val\_loss. ModelRegistry: register(bundle), get\_latest() \-\> ArtifactBundle, get\_by\_version(v). Manifest stored as JSON. ArtifactBundle.load() returns live encoder \+ FAISS index. CRITICAL: feature\_meta.json must be version-locked with encoder checkpoint. |
| :---- |

### **P2-M1 — KafkaIngestor / BatchAccumulator**

*Unchanged.*

| \[P2-M1 IngestionPipeline\] Consumers: KafkaIngestor/KinesisIngestor/PubSubIngestor all extend BaseIngestor.poll() \-\> List\[RawRecord\]. BatchAccumulator flushes every INGEST\_BATCH\_WIN\_SEC=300s \-\> EventBatch. Invalid events \-\> DeadLetterWriter (separate topic/file). Never crash on bad events. Key classes: BaseIngestor(ABC), BatchAccumulator, DeadLetterWriter. |
| :---- |

### **P2-M2 — RecordEncoder**

  **ACTION ITEM — Phase 1 Architecture Addendum**  

| Must be updated before Member B starts P2-M2 RecordEncoder MUST replicate the event-based preprocessing exactly (per-metric z-scoring, metric\_name vocabulary) sourced from the SAME global vocab maps and per-metric value stats used in training — never re-derive them independently at inference time. Update this primer and the corresponding Team Planner AI Prompt Brief before Member B starts, using Section 7 (P1-M3) of the Phase 1 Architecture Update Addendum as the source of truth. |
| :---- |
| \[P2-M2 RecordEncoder\]  (pending update \-- see callout above) Transforms RawRecord \-\> tensor (batch, seq\_len, ENC\_FEATURE\_DIM=256). CategoricalEncoder: vocab from feature\_meta.json, OOV \-\> UNK token. NumericalEncoder: LayerNorm. Time2Vec params from ArtifactBundle. MUST replicate training preprocessing exactly, including the new event-based schema (3 numeric / 4 categorical incl. metric\_name) once P1-M3 output is finalized. Load vocab+params via ArtifactBundle.load(). |

### **P2-M3 — InferenceEncoder**

*Unchanged.*

| \[P2-M3 InferenceEncoder\] TstccEncoder loaded from ArtifactBundle. eval() mode. ProjectionHead stripped. torch.no\_grad() on all forward passes. Chunk size=64 to prevent OOM. Input: (batch,seq\_len,256). Output: (batch,128) L2-norm float32. Warm-up: 3 dummy batches at \_\_init\_\_. Track P50/P95 latency per batch. |
| :---- |

### **P2-M4 — ReferenceEncoderService**

*Unchanged.*

| \[P2-M4 ReferenceEncoderService\] Same TstccEncoder as P2-M3. Encodes last REF\_HISTORY\_DAYS=90 days per entity. Produces per-entity centroid\_emb (mean of last 30 embs) \+ emb\_variance. Cold-start fallback: centroid=global\_mean, cold\_start\_flag=True. Writes EntityProfile to EntityStoreWriter. EMA update: alpha=REF\_CENTROID\_ALPHA=0.1. |
| :---- |

### **P2-M5 — CurrentEmbeddingAggregator**

*Unchanged.*

| \[P2-M5 CurrentEmbeddingAggregator\] Groups (batch,128) InferenceEncoder output by entity\_id. Mean-pools per entity then re-applies L2 normalisation (normalise AFTER mean, not before). Returns List\[CurrentEmbedding\]. Lightweight \-- no neural network. Key class: CurrentEmbeddingAggregator. Output dataclass: CurrentEmbedding. |
| :---- |

### **P2-M6 — RedisEntityStore**

*Unchanged.*

| \[P2-M6 EntityStore\] Redis primary. Keys: entity:{id}:current (float16 bytes), entity:{id}:centroid, entity:{id}:history (List). History: LPUSH+LTRIM to REDIS\_HISTORY\_LEN=30 atomically. Stats in Redis Hash. ISP: EntityStoreReader (reads only) \+ EntityStoreWriter (writes only) as separate interfaces. PgVectorEntityStore: secondary for analytical queries. Async methods via aioredis. |
| :---- |

### **P2-M7 — CosineDeviationScorer**

*Unchanged.*

| \[P2-M7 CosineDeviationScorer\] Inputs: CurrentEmbedding \+ EntityProfile from EntityStoreReader. global\_score \= 1 \- dot(current\_emb, centroid\_emb)  (both L2-norm so dot=cosine). local\_score \= mean(1 \- current\_emb @ history\_embs.T)  (vectorised). global\_flag \= global\_score \> SCORE\_GLOBAL\_THRESH=0.3. Returns DeviationResult. |
| :---- |

### **P2-M8 — MmdDriftMonitor**

*Unchanged.*

| \[P2-M8 MmdDriftMonitor\] MMD^2 with RBF kernel. Sigma via median heuristic. Subsample to 200 per distribution. Compares REF\_HISTORY\_DAYS=90d vs recent 30d embs from EntityStoreReader. ASYNC: AsyncDriftWorker runs in ThreadPoolExecutor. Result cached Redis TTL=REDIS\_DRIFT\_CACHE\_TTL=1800. AnomalyScorer reads cached DriftResult. is\_stale=True if cache expired \-\> use fallback 0.5. |
| :---- |

### **P2-M9 — EpisodeRetriever**

*Unchanged.*

| \[P2-M9 EpisodeRetriever\] FAISS IndexIVFFlat loaded from ArtifactBundle at startup. nprobe=FAISS\_N\_PROBE=20. search(query\_emb, k=FAISS\_TOP\_K=10, exclude\_entity\_id): L2 \-\> cosine: sim=1-dist^2/2. Returns SimilarityResult(mean\_similarity, episode\_matches). Cache Redis TTL=1800. Low mean\_similarity \-\> high novelty \-\> high anomaly contribution. |
| :---- |

### **P2-M10 — AnomalyScorer**

*Unchanged.*

| \[P2-M10 AnomalyScorer\] Input: ScoringInput(entity\_id, deviation\_result, drift\_result, similarity\_result). Formula: final\_score \= 0.4\*deviation\_score \+ 0.4\*drift\_score \+ 0.2\*(1-mean\_similarity). Severity from constants: \<SCORE\_SEV\_MEDIUM=0.3 \-\> LOW, \<HIGH=0.6 \-\> MED, \<CRIT=0.8 \-\> HIGH, else CRIT. Missing drift \-\> use is\_stale fallback=0.5. No similarity (new entity) \-\> similarity=0. |
| :---- |

### **P2-M11 — AlertDeduplicator**

*Unchanged.*

| \[P2-M11 AlertDeduplicator\] Fingerprint: hash(entity\_id, severity, cloud\_provider, top\_features\_sorted). Bucket: ts // REDIS\_DEDUP\_TTL=300. Redis key: dedup:{entity\_id}:{bucket}. Hit \-\> is\_duplicate=True, HINCRBY recurrence\_count. Miss \-\> new UUID4 incident\_id, SET TTL=300. Returns DedupResult. Duplicates suppress downstream alert; non-duplicates proceed. |
| :---- |

### **P2-M12 — CorrelationEngine**

*Unchanged.*

| \[P2-M12 CorrelationEngine\] NetworkX DiGraph. Nodes=entity\_ids with attrs (cloud\_provider, region, op\_id). Edges: \>=2 shared attrs \+ both alerted in last 10 min. Prune nodes inactive \>30 min. Community detection: nx.community.louvain\_communities() with random\_state=42. REGIONAL\_OUTAGE: group\_size\>10 AND same region. Returns CorrelationResult. |
| :---- |

### **P2-M13 — EscalationEngine**

*Unchanged.*

| \[P2-M13 EscalationEngine\] YAML rules in config/escalation\_rules.yaml. First-match wins. Order matters. Severity matrix: CRITICAL+REGIONAL \-\> SEV1, CRITICAL+ISOLATED \-\> SEV2, HIGH+CORRELATED \-\> SEV2, HIGH+ISOLATED \-\> SEV3, else SEV4. Business hours via entity timezone (IANA strings). Returns EscalationResult(sev\_level, target\_team, notify\_method, policy\_applied). |
| :---- |

### **P2-M14 — AlertApi / Notifiers**

*Unchanged.*

| \[P2-M14 AlertApi\] FastAPI. POST /alert accepts AlertPayload (Pydantic). Dispatches to List\[BaseNotifier\] injected via DIP. asyncio.gather(\*\[n.dispatch(payload) for n in notifiers\], return\_exceptions=True). SlackNotifier: Block Kit. EmailNotifier: SMTP HTML. PagerDutyNotifier: Events API v2. GET /alerts/recent (last 100 from Redis sorted set). WS /alerts/stream for dashboard. |
| :---- |

## **6c.  How to Use Primers in Prompts**

\--- PROMPT TEMPLATE \---  
\[CAPSTONE-189\]  
Project: Behavioral Anomaly Detection for multi-cloud (AWS/Azure/GCP/OCI).  
... (paste full global primer here)

\[P2-M7 CosineDeviationScorer\]  
... (paste module primer here)

TASK: Implement CosineDeviationScorer.compute\_scores(current\_emb: CurrentEmbedding,  
      profile: EntityProfile) \-\> DeviationResult.  
      Use vectorised numpy. Return DeviationResult with all fields populated.  
      Follow project conventions: snake\_case vars, \_score suffix for floats in \[0,1\].  
      Do not import from phase2/ \-- only from shared/types.py and shared/constants.py.

|  |  |
| :---- | :---- |
| **Tip** | **Why it saves tokens and improves output** |
| Always include global primer | Prevents LLM from using wrong conventions, wrong types, or wrong module structure. |
| Add module primer, not the full planner | Gives targeted context in \~5 lines vs 2000 words. Saves \~1500 tokens per prompt. |
| Name the exact class and method | 'Implement CosineDeviationScorer.compute\_scores()' gets better code than 'build the scorer'. |
| State import constraint explicitly | 'Only import from shared/types.py and shared/constants.py' prevents coupling violations. |
| State the return type | '-\> DeviationResult' tells the LLM exactly what the output shape must be. |
| Cite constants by name | 'Use SCORE\_GLOBAL\_THRESH not 0.3' keeps thresholds configurable in the generated code. |

Combine the global primer with one module primer to get targeted, correctly-integrated code generation. Example prompt structure:

*Team 189 · Capstone · Directory, Nomenclature & Design Principles Reference — updated for the Phase 1 Architecture Addendum*