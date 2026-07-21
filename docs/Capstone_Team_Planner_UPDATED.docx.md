**CAPSTONE PROJECT TEAM PLANNER**

*Behavioral Anomaly Detection Architecture – End to End*

Team 189 · 3 Members · 4-Week Sprint Plan · 20 Modules · 2 Phases · Full Dependency Mapping · Git Workflow

| Revision note This edition incorporates the Phase 1 Architecture Update Addendum. Updated content is marked with an orange UPDATED tag: Section 6 module guides P1-M1–P1-M4 (revised steps and AI Prompt Briefs), Section 7 Risk Register (two new realized risks), and a forward-looking note on P2-M2 (Record Encoding). Sections 1–5, Week 3–4 plans, Phase 2 module guides (P2-M3 onward), and Section 8 are unaffected and unchanged from the original plan. |
| :---- |

# **Table of Contents**

* 1\. Project Overview & Architecture Summary

* 2\. Module Dependency Map

* 3\. Team Role Assignments

* 4\. Git Workflow & Branching Strategy

* 5\. Week-by-Week Sprint Plan (4 Weeks)

* 6\. Module Implementation Guides (All 20 Modules)

* 7\. Risk Register & Watch Points

* 8\. Integration Checklist

# **1\. Project Overview & Architecture Summary**

*Unchanged.*

This document is the master project planner for Team 189's capstone: a Behavioral Anomaly Detection system for multi-cloud environments (AWS, Azure, GCP, OCI). The system detects unusual entity behavior by comparing current telemetry against historical behavioral embeddings learned via contrastive self-supervised learning.

## **The architecture has two distinct phases:**

* **Phase 1 – Pretraining (Offline):** Learns what normal behavior looks like using a contrastive encoder (TSTCC) trained on 1 month of historical minute-wise cloud telemetry. Outputs a trained encoder, a FAISS behavioral space, and a model registry bundle.

* **Phase 2 – Inference (Online):** Consumes live streaming events every 5–15 minutes, encodes them using the pretrained encoder, compares against each entity's behavioral baseline, computes a final anomaly score from three signals (Deviation, Drift, Similarity), and delivers explainable alerts via Slack / Email / PagerDuty / SIEM.

## **System Scope**

| Dimension | Details |
| :---- | :---- |
| Timeline | 4 weeks | \~80 person-hours total per member |
| Team Size | 3 members (Member A, B, C) with clearly assigned module ownership |
| Total Modules | 20 modules (6 in Phase 1, 14 in Phase 2\) |
| Cloud Coverage | AWS, Azure, GCP, OCI – all cloud providers |
| Primary Language | Python 3.10+, PyTorch 2.x, FastAPI |
| Storage | MongoDB Atlas (optional), Redis, PostgreSQL+PGVector, FAISS, AWS S3 |
| Alert Channels | Slack, Email, PagerDuty, SIEM / Dashboard (WebSocket) |

# **2\. Module Dependency Map**

*Unchanged.*

The table below shows every module's upstream dependencies. Focus on completing modules with the most dependents first — these are on the critical path. Modules marked CRITICAL must not be blocked.

| Module | Name | Owner | Priority | Depends On | Required By |
| :---- | :---- | :---- | :---- | :---- | :---- |
| P1-M1 | Historical Corpus | Member A – ML | CRITICAL | None — entry point of the system | P1-M2 |
| P1-M2 | Augmentation Pairs | Member A – ML | CRITICAL | P1-M1 (Historical Corpus output) | P1-M3 |
| P1-M3 | Contrastive Encoder (TSTCC) | Member A – ML | CRITICAL | P1-M2 (Augmented Pairs) | P1-M4, P2-M3, P2-M4 |
| P1-M4 | Contrastive Loss (NT-Xent / InfoNCE) | Member A – ML | CRITICAL | P1-M3 (Contrastive Encoder — embeddings output) | P1-M5 |
| P1-M5 | Behavioral Embedding Space | Member B – Inference | HIGH | P1-M4 (Trained Encoder Weights) | P1-M6, P2-M9 |
| P1-M6 | Outcome / Model Registry | Member B – Inference | HIGH | P1-M3, P1-M4, P1-M5 (all training outputs) | P2-M3, P2-M4 |
| P2-M1 | Periodic Batch Ingestion | Member B – Inference | HIGH | P1-M6 (schema knowledge from model registry) | P2-M2 |
| P2-M2 | Record Encoding | Member B – Inference | HIGH | P1-M6 (feature metadata for embedding tables), P2-M1 (event batches) | P2-M5 |
| P2-M3 | Retrieved Encoder (Inference) | Member C – Detection | HIGH | P1-M6 (encoder weights .pt), P2-M2 (record embeddings as input) | P2-M5 |
| P2-M4 | Pretrained Encoder (Reference) | Member C – Detection | HIGH | P1-M6 (encoder weights .pt), P2-M2 (historical record embeddings as input) | P2-M6 |
| P2-M5 | Current Embedding | Member B – Inference | CRITICAL | P2-M3 (Inference Encoder output) | P2-M6, P2-M7 |
| P2-M6 | Dynamic Entity Store | Member B – Inference | CRITICAL | P2-M4 (reference embeddings written on startup), P2-M5 (current embeddings written per batch) | P2-M7, P2-M8, P2-M9 |
| P2-M7 | Cosine Distance | Member B – Inference | CRITICAL | P2-M5 (current embedding), P2-M6 (centroid and history) | P2-M10 |
| P2-M8 | MMD Drift Monitor | Member B – Inference | HIGH | P2-M6 (history embeddings — past 90 days vs recent 30 days) | P2-M10 |
| P2-M9 | Retrieved Similar Episodes | Member C – Detection | HIGH | P1-M5 (FAISS index), P2-M5 (current embedding as query) | P2-M10 |
| P2-M10 | Final Anomaly Score | Member C – Detection | CRITICAL | P2-M7 (deviation), P2-M8 (drift), P2-M9 (similarity) | P2-M11 |
| P2-M11 | Deduplication | Member C – Detection | MEDIUM | P2-M10 (AnomalyResult) | P2-M12 |
| P2-M12 | Correlation Engine | Member C – Detection | MEDIUM | P2-M11 (DedupResult with canonical incident IDs) | P2-M13 |
| P2-M13 | Escalation Engine | Member C – Detection | HIGH | P2-M12 (CorrelationResult — group\_type and severity) | P2-M14 |
| P2-M14 | Explainable Alert API | Member C – Detection | CRITICAL | P2-M13 (EscalationResult), P2-M10 (component scores), P2-M9 (similar episodes), P2-M12 (related incidents) | — Terminal |

**Critical Path (must complete in order):** 

**P1-M1 → P1-M2 → P1-M3 → P1-M4 → P1-M5 → P1-M6 → \[Deploy to Inference\] → P2-M1 → P2-M2 → P2-M5 → P2-M6 → P2-M7 → P2-M10 → P2-M11 → P2-M12 → P2-M13 → P2-M14**

Parallel paths that can be built concurrently: P2-M8 (MMD Drift, async) and P2-M9 (Episode Retrieval, from FAISS index) can be developed in parallel with P2-M6 and P2-M7.

# **3\. Team Role Assignments**

*Unchanged.*

The team is split into three vertical ownership tracks. Each member owns their modules end-to-end (design, implement, test, integrate). Shared infrastructure (types.py, config.yaml, Docker setup) is co-owned.

| Member | Role | Modules Owned | Focus Area |
| :---- | :---- | :---- | :---- |
| Member A | ML Training Lead | P1-M1, P1-M2, P1-M3, P1-M4 | Data pipeline, model training, augmentation, loss function, model artifacts |
| Member B | Inference & Storage Lead | P1-M5, P1-M6, P2-M1, P2-M2, P2-M5, P2-M6, P2-M7, P2-M8 | Streaming ingestion, record encoding, entity store, embedding comparison, drift detection |
| Member C | Detection & Alerting Lead | P2-M3, P2-M4, P2-M9, P2-M10, P2-M11, P2-M12, P2-M13, P2-M14 | Episode retrieval, final scoring, deduplication, correlation, escalation, alert API |

## **Module Count Balance:**

* Member A: 4 modules (P1-M1, P1-M2, P1-M3, P1-M4) — heaviest ML work; module complexity compensates for count

* Member B: 7 modules (P1-M5, P1-M6, P2-M1, P2-M2, P2-M5, P2-M6, P2-M7, P2-M8) — infrastructure heavy, many are lower complexity

* Member C: 8 modules (P2-M3, P2-M4, P2-M9, P2-M10, P2-M11, P2-M12, P2-M13, P2-M14) — alerting pipeline, several are lightweight

All members have roughly equal estimated effort (\~80h each). Member A's modules are individually the most complex (ML training).

# **4\. Git Workflow & Branching Strategy**

*Unchanged.*

## **Repository Structure**

Initialize a single monorepo with clear module folders. Suggested structure:

| Directory / File | Contents |
| :---- | :---- |
| phase1/ | All training modules: corpus.py, augmentation.py, encoder.py, loss.py, embedding\_space.py, registry.py |
| phase2/ingestion/ | ingestion.py, batch\_accumulator.py, schema\_validator.py |
| phase2/encoding/ | record\_encoder.py, inference\_encoder.py, reference\_encoder.py |
| phase2/store/ | entity\_store.py, redis\_client.py, pgvector\_client.py |
| phase2/detection/ | cosine\_scorer.py, mmd\_monitor.py, episode\_retriever.py, anomaly\_scorer.py |
| phase2/alerting/ | deduplication.py, correlation.py, escalation.py, alert\_api.py |
| shared/ | types.py, config.py, constants.py — shared dataclasses and config loading |
| tests/ | unit/, integration/, e2e/ — pytest test files mirroring module structure |
| notebooks/ | data\_exploration.ipynb, training\_monitor.ipynb, alert\_dashboard.ipynb |
| config/ | config.yaml (all hyperparams), escalation\_rules.yaml, feature\_meta.json |
| docker-compose.yml | Redis, Kafka, PostgreSQL local dev environment |
| requirements.txt | All Python dependencies pinned to specific versions |

## **Branching Strategy (GitHub Flow)**

Use GitHub Flow: a protected main branch with feature branches per module. No direct pushes to main.

| Branch Pattern | Purpose & Rules |
| :---- | :---- |
| main | Protected. Requires 1 PR approval \+ passing CI. Only merge on milestones. Always deployable. |
| dev | Integration branch. All feature branches merge here first. CI runs on every push. Team reviews integration. |
| feature/P1-M1-corpus | One branch per module. Named: feature/{module-id}-{short-name}. Owner creates, implements, tests, and opens PR to dev. |
| fix/entity-store-ttl | Bug fixes found during integration. Branch from dev, fix, PR back to dev. |
| release/week-N | End-of-week release tag. Created from dev → main once milestone is verified. |

## **Git Conventions**

* Commit messages: feat(P1-M3): add Time2Vec layer with k=8 sinusoidal encoding | fix(P2-M6): fix Redis LTRIM race condition in history rotation | test(P2-M10): add unit tests for anomaly score formula edge cases

* PRs must include: description of what was built, how to test it, and any integration contracts that changed (e.g., output schema changed)

* Every PR must add at least one unit test. PRs without tests will not be merged.

* Use GitHub Issues to track blockers. Label them: blocker, integration, question, performance

* CODEOWNERS file: each module directory owned by the responsible member — auto-assigns them for review

## **CI/CD Pipeline (GitHub Actions)**

* On every push to any branch: run pytest tests/ (unit tests only, \< 60 seconds)

* On push to dev: run pytest tests/ including integration tests (requires Docker services via docker-compose)

* On merge to main: run full e2e test suite \+ optional model inference smoke test

* Required checks before merge: all tests pass, no import errors, flake8 linting

# **5\. Week-by-Week Sprint Plan**

*Unchanged.*

## **Week 1: Foundation, Scaffolding & Data**

**Goal:** Establish project repo structure, shared type contracts, and core data pipeline. Each member builds their foundational layer so Week 2 can focus on ML logic.

### **Milestones to Hit by End of Week:**

* Git repo initialized with branch protection and PR templates

* Shared types module (types.py) committed with all inter-module dataclasses

* P1-M1 Historical Corpus loader producing validated batches

* P1-M2 Augmentation Pairs producing (view\_1, view\_2) tensors from sample data

* P2-M11 Deduplication scaffold with Redis integration working

* P2-M3 and P2-M4 model loading scaffolds returning dummy embeddings

* P2-M2 Record Encoding schema \+ vocabulary loading from feature metadata

| Member | Week 1 Tasks |
| :---- | :---- |
| Member A — ML Training Lead | P1-M1: Historical Corpus loader (Parquet \+ JSON, schema validation). P1-M2: Augmentation Pairs (Temporal Jitter \+ Attribute Masking \+ PairGenerator). Setup: local data directory structure, sample data generation. |
| Member B — Inference & Storage Lead | P2-M2: RecordEncoder schema design \+ vocabulary loading scaffold. Shared types: define all inter-module dataclasses in shared/types.py. Environment: Docker setup for Redis \+ Kafka local dev. |
| Member C — Detection & Alerting Lead | Repo: Git repo setup, branch rules, PR template, CODEOWNERS. P2-M3/M4: EncoderInference scaffold (model loading \+ dummy forward pass). P2-M11: Deduplication MVP with MinHash \+ Redis TTL. |

## **Week 2: Core ML & Inference Backbone**

**Goal:** Train the contrastive encoder and build the core inference pipeline. Phase 1 training should produce the first model checkpoint by end of week.

### **Milestones to Hit by End of Week:**

* TSTCC encoder architecture implemented and forward pass verified

* NT-Xent loss implemented, first training run completes (even if on small data)

* FAISS behavioral embedding space indexed with sample embeddings

* P2-M1 Batch Ingestion consuming from local Kafka topic

* P2-M5 Current Embedding pipeline producing 128-d embeddings from live records

* P2-M9 Episode Retriever returning Top-K results from FAISS

| Member | Week 2 Tasks |
| :---- | :---- |
| Member A — ML Training Lead | P1-M3: Contrastive Encoder (TSTCC full architecture \+ Time2Vec \+ GRU \+ Attention \+ Projection). P1-M4: NT-Xent / InfoNCE loss \+ training loop \+ AdamW \+ LR schedule \+ checkpointing. |
| Member B — Inference & Storage Lead | P2-M1: Periodic Batch Ingestion (Kafka consumer \+ batch accumulator \+ schema validation). P2-M5: CurrentEmbeddingAggregator (mean pooling \+ L2 norm per entity per batch). |
| Member C — Detection & Alerting Lead | P2-M9: EpisodeRetriever (FAISS kNN search \+ L2→cosine conversion \+ caching). P2-M4: ReferenceEncoderService (historical batch encoding \+ per-entity centroid computation). |

## **Week 3: Detection Engine & Entity Store**

**Goal:** Complete Phase 1 artifacts, build the full entity store, and implement all anomaly scoring components. End of week: first end-to-end anomaly score should be computable.

### **Milestones to Hit by End of Week:**

* P1-M5 FAISS behavioral embedding space built and serialized

* P1-M6 Model Registry packaging all training artifacts

* P2-M6 Dynamic Entity Store operational (Redis \+ PGVector)

* P2-M7 Cosine Distance scorer returning DeviationScore

* P2-M10 Final Anomaly Score computed for sample entities

* P2-M12 Correlation Engine grouping alerts in NetworkX

| Member | Week 3 Tasks |
| :---- | :---- |
| Member A — ML Training Lead | P1-M5: Behavioral Embedding Space (batch encode corpus \+ FAISS index build \+ metadata tagging). P1-M6: Model Registry (artifact bundle \+ versioned manifest \+ one-command loader). |
| Member B — Inference & Storage Lead | P2-M6: Dynamic Entity Store (Redis schema \+ EMA centroid \+ history rotation \+ PGVector secondary). P2-M7: Cosine Distance scorer (global \+ local deviation \+ thresholds). |
| Member C — Detection & Alerting Lead | P2-M10: Final Anomaly Score (weighted formula \+ severity mapping \+ component breakdown). P2-M12: Correlation Engine (entity-attribute graph \+ community detection \+ group typing). |

## **Week 4: Alerting, Integration & End-to-End Testing**

**Goal:** Complete all alert delivery modules, run full end-to-end integration tests, fix integration bugs, prepare demo. Every module should be connected and data should flow from ingestion to alert.

### **Milestones to Hit by End of Week:**

* P2-M8 MMD Drift Monitor async computation working with Redis caching

* P2-M13 Escalation Engine applying YAML rules and assigning teams

* P2-M14 FastAPI Alert API delivering to Slack and Email

* Full end-to-end test: synthetic event → ingestion → encoding → scoring → alert

* Dashboard showing live alerts via WebSocket

* Documentation: README, API docs, architecture diagram updated

| Member | Week 4 Tasks |
| :---- | :---- |
| Member A — ML Training Lead | Integration testing: run full pipeline on synthetic dataset, fix data format issues. Documentation: README, setup guide, architecture diagram. Performance: profiling and optimization of bottlenecks. |
| Member B — Inference & Storage Lead | P2-M8: MMD Drift Monitor (async worker \+ ThreadPoolExecutor \+ Redis cache \+ null calibration). Integration: wire P2-M7 \+ P2-M8 scores into P2-M10 ScoringInput. |
| Member C — Detection & Alerting Lead | P2-M13: Escalation Engine (YAML rules \+ business hours \+ team assignment). P2-M14: FastAPI Alert API (Slack \+ Email \+ PagerDuty \+ WebSocket dashboard). End-to-end test: inject synthetic anomalies, verify alerts are delivered. |

# **6\. Module Implementation Guides**

| Revision note P1-M1 through P1-M4 below reflect the AS-BUILT Phase 1 implementation per the Phase 1 Architecture Update Addendum. Revised Implementation Steps and AI Prompt Briefs REPLACE the corresponding original subsections; 'What to Watch Out For' lists are APPENDED to, not replaced — the original risks are still valid. P1-M5 onward are unaffected. |
| :---- |

## **P1-M1 — Historical Corpus**

*Status: unchanged, complete. Phase 1 – Pretraining (Offline). Owner: Member A, ML Training Lead. Sprint Week 1\. Priority: CRITICAL.*

| No implementation changes CorpusIterator remains complete with 41 passing unit tests, handling resource\_inventory, heatstack, and operations\_governance collections. Confirmed NOT affected by the redesign — its output schema (RawRecord) already supported the new 3-numeric/4-categorical shape. |
| :---- |

**Overview:** Build the data loading layer for historical Parquet and JSON minute-wise records. Establish schema validation, deduplication logic, and write the corpus iterator.

**Tech Stack:** Python, Pandas, Parquet, AWS S3 / HDFS / ADLS

**Depends On:** None — entry point of the system

### **Implementation Steps:**

* Define canonical schema (entity\_id, timestamp, categorical fields, numerical fields, source cloud)

* Write loaders for both Parquet (pandas read\_parquet) and JSON (streaming with ijson for large files)

* Validate schema on load: dtype checks, null-value thresholds, timestamp format enforcement (ISO \+00:00 / Z variants)

* Build a CorpusIterator class that yields fixed windows (e.g., 1-minute buckets) for downstream use

* Write unit tests: load 1K rows Parquet, assert schema; load 500 JSON rows, assert schema

* Push raw records to S3/local HDFS directory in normalized Parquet format (single schema)

### **Integration with the Rest of the System:**

Outputs are fed directly into P1-M2 (Augmentation Pairs). Ensure the CorpusIterator is importable as a module (corpus.py) and returns a consistent dict structure.

### **AI Prompt Brief for Implementation:**

*You are building a data ingestion layer for a cloud telemetry corpus. The schema has: entity\_id (str), timestamp (ISO8601), op\_id (str, Zipf-distributed), region (str), cloud\_provider (str: AWS/Azure/GCP/OCI), numeric\_features (float array), categorical\_features (dict). Write a Python class CorpusIterator that lazily loads Parquet/JSON files, validates the schema, normalizes timestamps to UTC, deduplicates by (entity\_id, timestamp), and yields batches of N records as dicts.*

### **What to Watch Out For:**

* Timestamp format inconsistency between Parquet and JSON sources — enforce normalization early (pd.to\_datetime(..., utc=True))

* File size: 1-month minute-wise data for multi-cloud can be 10–50 GB. Use chunked reading (chunksize param in read\_parquet)

* Schema drift between cloud providers — build a provider-specific field mapper

## **P1-M2 — StreamingAugPairsDataset (formerly Augmentation Pairs / PairGenerator)**

  **UPDATED — Phase 1 Architecture Addendum**  

*Status: superseded by streaming approach. Phase 1 – Pretraining (Offline). Owner: Member A, ML Training Lead. Sprint Week 1\. Priority: CRITICAL.*

| Change The plan's two-stage design (PairGenerator produces static .npz pair files, consumed later by training) was replaced by on-the-fly windowing inside StreamingAugPairsDataset. Augmentation (temporal jitter, attribute masking) is assumed to already be baked into aug\_pairs.parquet's pair\_id/view columns upstream; this module's remaining responsibility is turning long-format event rows into fixed-length (view\_a, view\_b) sequence windows per entity, per epoch, without loading the full file into memory. |
| :---- |

**Tech Stack:** Python, PyArrow, PyTorch IterableDataset

**Depends On:** P1-M1 (Historical Corpus output, materialized as aug\_pairs.parquet upstream)

### **Revised Implementation Steps:**

* Open aug\_pairs.parquet as a pq.ParquetFile; read num\_row\_groups only at construction — do not store the open file handle on self (breaks Windows multiprocessing, see Section 7 Risk Register)

* On \_\_iter\_\_, shard row groups round-robin across DataLoader workers via get\_worker\_info()

* Per row group: z-score 'value' using GLOBAL per-metric stats (from compute\_metric\_value\_stats(), computed once for the whole file, not per row group)

* Encode all 4 categorical columns using GLOBAL vocab maps (from compute\_vocab\_sizes())

* Split into view='a' / view='b', group by entity\_id, sort by (pair\_id, timestamp, metric\_name)

* Build sliding windows of seq\_len consecutive EVENTS (not timestamps) with configurable stride; shuffle window order within the row group

* Yield (numeric, categorical, timestamps) dict pairs; free the row group's DataFrame before moving to the next

### **Integration with the Rest of the System:**

Outputs (view\_a, view\_b) windows feed directly into the Contrastive Encoder (P1-M3) via contrastive\_collate\_fn(). Window shapes must match the encoder's input layer contract (batch, seq\_len, feature\_dim), where feature\_dim is now built from 3 numeric \+ 4 categorical fields rather than the originally planned 14 numeric \+ 3 categorical fields.

### **Revised AI Prompt Brief for Implementation:**

*Implement a PyTorch IterableDataset, StreamingAugPairsDataset, that streams aug\_pairs.parquet row-group by row-group (never loading the full file). Each row is ONE (timestamp, metric\_name, value) reading event, not a fixed-width timestep. Z-score 'value' per metric\_name using precomputed global stats. Encode cloud/entity\_type/namespace/metric\_name via precomputed global vocab maps. Build sliding windows of seq\_len consecutive events per entity across matched view='a'/view='b' pairs. CRITICAL: do not store an open pyarrow.parquet.ParquetFile as an instance attribute set in \_\_init\_\_ — open it lazily per-process, or DataLoader(num\_workers\>0) will crash on Windows with a pickling TypeError.*

### **What to Watch Out For:**

* Temporal jitter can create overlapping windows — add bounds checking to prevent view timestamps from crossing episode boundaries

* If categorical cardinality is high (\>1000 unique op\_ids), attribute masking logic needs to handle sparse representations

* Semi-hard negatives require entity index lookups — cache entity→window index at augmentation time, not at batch time

* **\[NEW\]** Never store an open pyarrow.parquet.ParquetFile as an \_\_init\_\_ instance attribute — it is unpicklable on Windows spawn and will crash any worker-based training. Open it lazily per-process instead.

* **\[NEW\]** seq\_len now means consecutive reading EVENTS, not distinct timesteps — a naive port of the old windowing logic will silently produce the wrong window semantics.

## **P1-M3 — TstccEncoder (Contrastive Encoder)**

  **UPDATED — Phase 1 Architecture Addendum**  

*Status: redesigned, training. Phase 1 – Pretraining (Offline). Owner: Member A, ML Training Lead. Sprint Week 2\. Priority: CRITICAL.*

| Change Input contract changed from 14 numeric \+ 3 categorical to 3 numeric \+ 4 categorical. Internal architecture (EmbeddingLayer → Time2Vec(k=8) → GRU(2×128) → AttentionPooling → ProjectionHead) is UNCHANGED — only the width and composition of the input embedding layer changed to accommodate metric\_name. |
| :---- |

**Overview:** Build the TSTCC neural network encoder: Embedding Layer → Time2Vec (k=8) → GRU Encoder (2 layers, hidden=128) → Attention Pooling → Projection Layer (d=128). This is the core model.

**Tech Stack:** PyTorch

**Depends On:** P1-M2 (StreamingAugPairsDataset output)

### **Revised Implementation Steps (delta from original plan):**

* build\_tstcc\_encoder\_for\_aug\_pairs() now takes metric\_name\_vocab\_size\_int as a required 4th vocab-size argument, computed from the FULL file via compute\_vocab\_sizes() — not sampled from one row group, since metric cardinality varies by resource type across row groups

* EmbeddingLayerConfigData.num\_numeric\_int is now 3 (was 14\) — AUG\_PAIRS\_NUM\_NUMERIC constant, see Directory Structure Section 2d

* CategoricalFieldConfigData list now has 4 entries; embed\_dim per field still uses the existing heuristic: max(4, min(vocab\_size // 2, 32))

* Checkpoint save/load format (state\_dict \+ epoch\_int \+ loss\_float) is UNCHANGED and backward-compatible in structure, but checkpoints trained on the OLD 14/3 schema cannot be loaded into the new 3/4 architecture — shape mismatch on the embedding and numeric-projection layers

* Implement GRU Encoder: 2-layer GRU, hidden\_size=128, bidirectional=False, with dropout=0.1 (unchanged)

* Implement AttentionPooling: single-head attention over GRU hidden states → context vector (unchanged)

* Implement ProjectionHead: Linear(128→128) → ReLU → Linear(128→128) for contrastive space (unchanged)

* Add model checkpointing: save every 5 epochs to model\_registry/ (unchanged)

| Training status as of the addendum Epoch 10 of 20 complete under the new schema. Avg. NT-Xent loss: 0.2552 (epoch 1\) → 0.0240 (epoch 10), 90.6% reduction, still decreasing at epoch 11\. Collapse diagnostic run against the epoch-10 checkpoint (synthetic-schema inputs, pending real-batch validation): positive-pair cosine similarity 0.84 vs. negative-pair 0.28 — healthy separation, no representation collapse detected. |
| :---- |

### **Integration with the Rest of the System:**

The encoder must export save\_weights(path) and load\_weights(path) methods. The same class is loaded in P2-M3 (inference) and P2-M4 (reference). Output embeddings feed into P1-M4 (Loss) during training and P2-M5 (Current Embedding) during inference. The Phase 1 output contract — a trained encoder producing 128-d L2-normalised embeddings — is UNCHANGED; only the encoder's INPUT shape changed.

### **Revised AI Prompt Brief for Implementation:**

*Implement a TSTCC contrastive encoder in PyTorch. Architecture: (1) EmbeddingLayer that encodes 4 categorical fields (cloud, entity\_type, namespace, metric\_name) via nn.Embedding and 3 numeric fields (value\_norm, hour\_of\_day, day\_of\_week) via nn.Linear, concatenating to feature\_dim=256, (2) Time2Vec layer with k=8 (1 linear \+ 7 sine terms applied to normalized timestamps), (3) 2-layer GRU (hidden=128, dropout=0.1), (4) AttentionPooling that produces a single context vector from GRU outputs, (5) ProjectionHead (Linear→ReLU→Linear, output\_dim=128). Input: (batch\_size, seq\_len, feature\_dim). Output: normalized L2 embedding (batch\_size, 128). metric\_name\_vocab\_size\_int must be computed from a full-file pass (compute\_vocab\_sizes()), not sampled from one row group. Include save/load checkpoint methods.*

### **What to Watch Out For:**

* Time2Vec initialization is sensitive — use small random init for sine frequencies, not uniform

* GRU with variable-length sequences requires pack\_padded\_sequence / pad\_packed\_sequence — implement from the start

* Projection head must output L2-normalized vectors for NT-Xent loss to work correctly — add F.normalize() at the end

* **\[NEW\]** Checkpoints trained under the OLD 14-numeric/3-categorical schema cannot be loaded into the new 3/4 architecture — shape mismatch on embedding and numeric-projection layers. Do not attempt to warm-start from old checkpoints.

* **\[NEW\]** Re-run the collapse diagnostic against a REAL held-out batch from aug\_pairs.parquet, not synthetic schema-matched inputs, before treating the encoder as validated.

## **P1-M4 — NTXentLossComputer / train\_tstcc.py (formerly NtXentLoss / TrainingLoop)**

  **UPDATED — Phase 1 Architecture Addendum**  

*Status: running, epoch 10/20. Phase 1 – Pretraining (Offline). Owner: Member A, ML Training Lead. Sprint Week 2\. Priority: CRITICAL.*

| Change Structurally reorganized (see Directory Structure Addendum Section 3\) but functionally matches the original plan: AdamW \+ CosineAnnealingLR \+ grad clipping at max\_norm=1.0. The class name is NTXentLossComputer rather than the planned NtXentLoss; there is no standalone TrainingLoop or CosineLrScheduler class — both are inlined into train\_tstcc.py's main(). |
| :---- |

**Overview:** Implement the NT-Xent / InfoNCE contrastive loss function. Pull positive pairs together, push apart negative pairs, with temporal negatives from the same entity treated as semi-hard negatives.

**Tech Stack:** PyTorch

**Depends On:** P1-M3 (Contrastive Encoder — embeddings output)

### **Implementation Steps:**

* Implement NTXentLossComputer(temperature=0.07): compute similarity matrix, mask out diagonals, compute cross-entropy over positive pairs

* Add temporal negatives masking: same entity, same session → excluded from negative pool

* Implement training in train\_tstcc.py main(): AdamW optimizer (lr=TRAIN\_LR — see open reconciliation item below, weight\_decay=1e-4), CosineAnnealingLR scheduler (T\_max=20 epochs)

* Add gradient clipping (max\_norm=1.0) to prevent exploding gradients in GRU

* Log training loss, positive similarity, negative similarity to wandb/tensorboard every 100 steps

* Save best model checkpoint based on validation loss; checkpoint every 5 epochs to model\_registry/

### **Confirmed Configuration:**

| Parameter | Value |
| :---- | :---- |
| Optimizer | AdamW |
| Initial LR | 3e-4 (plan specified 1e-4 — verify with Member A whether this was an intentional tune) |
| LR Schedule | CosineAnnealingLR, T\_max \= 20 epochs |
| Gradient Clipping | max\_norm \= 1.0 (matches plan) |
| Checkpoint Frequency | Every 5 epochs → model\_registry/ |
| Batches per Epoch | 8,651 |
| **Open reconciliation item — TRAIN\_LR** TRAIN\_LR is documented as 1e-4 in the original shared/constants.py registry, but the running training job uses 3e-4. Confirm which is correct and update whichever source is stale before Member A hands off P1-M5/P1-M6. |  |

### **Integration with the Rest of the System:**

Loss function is used only during Phase 1 training. Once training is done, only the encoder weights (without projection head) are saved for Phase 2 inference. Coordinate with P1-M5 on what the trained encoder weights format looks like.

### **AI Prompt Brief for Implementation:**

*Implement NT-Xent (InfoNCE) contrastive loss in PyTorch as a class NTXentLossComputer with an accompanying NTXentLossConfigData dataclass. Inputs: z\_i and z\_j are L2-normalized embedding tensors (batch\_size, 128\) for view\_a and view\_b. Compute pairwise cosine similarity matrix, apply temperature scaling (tau=0.07), mask positives on diagonal, treat all other pairs in the batch as negatives. Add support for temporal negative masking: pass an entity\_ids tensor and a session\_ids tensor; pairs from the same (entity\_id, session\_id) are excluded from the negative pool. Return scalar loss. Also implement the training entry point as a main() function inside train\_tstcc.py (not a standalone TrainingLoop class) using AdamW, torch.optim.lr\_scheduler.CosineAnnealingLR directly (no standalone scheduler class), and gradient clipping.*

### **What to Watch Out For:**

* Batch size is critical for NT-Xent — small batches (\<256) lead to poor negative sampling. Use gradient accumulation if GPU memory is limited

* Temporal negative masking can accidentally exclude too many negatives for high-frequency entities — add a min\_negatives check

* Float16 training (AMP) can cause numerical instability in the log-softmax — keep loss computation in float32

* **\[NEW\]** Finish the remaining training epochs (11 → 20\) before treating the model as final — cosine annealing's final epochs perform meaningful fine-grained refinement; stopping early forfeits it.

## **P1-M5 — Behavioral Embedding Space**

*Unaffected by the redesign — proceeds exactly as originally planned (consumes already-produced 128-d embeddings, not raw features). Phase 1 – Pretraining (Offline). Owner: Member B, Inference & Storage Lead. Sprint Week 2\. Priority: HIGH.*

**Overview:** Build and index the behavioral embedding space. Run all historical records through the trained encoder to generate 128-d embeddings, then index them in FAISS for fast similarity search at inference time.

**Tech Stack:** FAISS / ScaNN, NumPy

**Depends On:** P1-M4 (Trained Encoder Weights)

### **Implementation Steps:**

* Load trained encoder weights (from P1-M4 output) in inference mode (encoder only, no projection head)

* Batch-encode all historical records → numpy array of shape (N, 128\)

* Build FAISS IndexFlatL2 or IndexIVFFlat (for large N \> 1M) index from embeddings

* Tag each embedding with metadata: entity\_id, timestamp, cloud\_provider, severity label (if available)

* Serialize index to disk: faiss.write\_index(index, 'behavioral\_space.faiss')

* Optionally build ScaNN index as alternative for cloud deployment

* Write visualizer: UMAP projection of embedding space, colored by cloud provider and entity type

### **Integration with the Rest of the System:**

The FAISS index is used by P2-M9 (Retrieved Similar Episodes) for Top-K historical episode retrieval at inference time. The index file path and metadata JSON must be registered in the model registry (P1-M6). Share the index loading utility (faiss\_utils.py) with Member C who owns P2-M9.

### **AI Prompt Brief for Implementation:**

*You have a trained TSTCC encoder that maps telemetry records to 128-d L2-normalized embeddings. Build a behavioral embedding index: (1) Write a BatchEncoder class that loads the encoder, disables projection head, runs records through in batches of 512, returns numpy array (N,128), (2) Build a FAISS IndexIVFFlat with nlist=100 trained on the embedding corpus, (3) Add an EmbeddingStore class that wraps the index and supports: add(embeddings, metadata), search\_topk(query\_embedding, k=10) → returns (distances, indices, metadata\_list), save(path), load(path). Include unit test: encode 100 random records, verify search returns nearest neighbor as the same record.*

### **What to Watch Out For:**

* FAISS IVF index requires training before adding vectors — build on a random 10% sample first, then add all

* For N \> 5M records, IndexIVFPQ (product quantization) is needed or memory will explode

* The UMAP visualization is optional — don't block P1-M6 on it

## **P1-M6 — Outcome / Model Registry**

*Unaffected by the redesign. Phase 1 – Pretraining (Offline). Owner: Member B, Inference & Storage Lead. Sprint Week 3\. Priority: HIGH.*

**Overview:** Package all training artifacts into a versioned model registry entry. Artifacts include: TSTCC encoder weights (.pt), FAISS index, config (YAML/JSON), feature metadata, and Time2Vec parameters.

**Tech Stack:** MLflow / S3 / JSON

**Depends On:** P1-M3, P1-M4, P1-M5 (all training outputs)

### **Implementation Steps:**

* Define ArtifactBundle schema: model\_version, encoder\_path, faiss\_index\_path, config\_path, feature\_meta\_path, time2vec\_params\_path, training\_date, val\_loss

* Write a ModelRegistry class: register(bundle), get\_latest(), get\_by\_version(v)

* Store registry manifest as artifacts\_manifest.json in S3 or local model\_registry/ folder

* Save feature metadata: field names, categorical vocabularies (entity\_id→int mapping), numerical scaler params

* Write a one-command loader: ArtifactBundle.load\_latest() returns encoder \+ FAISS index \+ metadata ready for inference

* Version using semantic versioning (0.1.0 \= first trained model)

### **Integration with the Rest of the System:**

P2-M3 and P2-M4 both call ArtifactBundle.load\_latest() to load the encoder. P2-M9 uses the FAISS index from the bundle. This module is the handoff point between Phase 1 and Phase 2\.

### **AI Prompt Brief for Implementation:**

*Implement a lightweight model registry for a ML anomaly detection system. Requirements: (1) ArtifactBundle dataclass with fields: version (str), encoder\_path (Path), faiss\_index\_path (Path), config (dict), feature\_meta (dict), time2vec\_params (dict), training\_timestamp (datetime), val\_loss (float), (2) ModelRegistry class that stores bundles in a JSON manifest file, supports register(bundle), list\_versions(), get\_latest() → ArtifactBundle, get\_by\_version(v), (3) ArtifactBundle.load() method that instantiates the TSTCC encoder with loaded weights, (4) Save/load the registry from S3 or local path based on config flag. Include a CLI: python registry.py \--register \--encoder path/to/weights.pt*

### **What to Watch Out For:**

* If multiple team members run training simultaneously, the registry manifest can have write conflicts — add file locking or use MLflow

* Feature metadata (vocabulary mappings) MUST match exactly between training and inference — version control this file with the model, never separately

## **P2-M1 — Periodic Batch Ingestion**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member B, Inference & Storage Lead. Sprint Week 2\. Priority: HIGH.*

**Overview:** Build the streaming ingestion layer. Consume events from Kafka/Kinesis/PubSub every 5–15 minutes, batch them, validate against schema, and deliver event batches to the Record Encoder.

**Tech Stack:** Kafka / Kinesis / PubSub, Python, Avro / JSON

**Depends On:** P1-M6 (schema knowledge from model registry)

### **Implementation Steps:**

* Implement KafkaConsumer wrapper (confluent-kafka-python) with configurable topic, group\_id, poll interval

* Implement KinesisConsumer and PubSubConsumer as alternative adapters (same interface, IngestorAdapter ABC)

* Implement batch accumulator: collect events for 5 minutes (configurable), then flush to the encoding queue

* Validate each event against the canonical schema (reuse schema validator from P1-M1)

* Write dead-letter queue (DLQ) handler: malformed events go to a separate Kafka topic / log file

* Add health metrics: events\_received/s, validation\_error\_rate, batch\_lag\_seconds

### **Integration with the Rest of the System:**

Output is a Python queue (multiprocessing.Queue or asyncio Queue) of validated event batches. P2-M2 (Record Encoding) consumes this queue. Use a shared BatchEvent dataclass defined in shared/types.py to avoid coupling.

### **AI Prompt Brief for Implementation:**

*Build a multi-source streaming ingestion layer for cloud telemetry events. Implement: (1) IngestorAdapter abstract class with methods: start(), stop(), poll(timeout\_ms) → List\[Event\], (2) KafkaIngestor(IngestorAdapter) using confluent-kafka with configurable bootstrap\_servers, topic, group\_id, (3) BatchAccumulator that collects events for window\_seconds (default 300\) then emits a batch, (4) SchemaValidator that validates each event against the canonical schema (entity\_id, timestamp, op\_id, region, cloud\_provider, numeric\_features, categorical\_features), (5) DeadLetterWriter that logs invalid events to file. Wire these together in an IngestionPipeline class with start\_async() method.*

### **What to Watch Out For:**

* Kafka consumer group management — ensure each consumer in the team's test cluster has a unique group\_id to avoid offset conflicts

* Batch window of 5 min is configurable — for demo, reduce to 30 seconds to iterate faster

* Schema validation failures in production can be high (new cloud events, unknown op\_ids) — design DLQ before assuming 100% valid input

## **P2-M2 — Record Encoding (RecordEncoder)**

  **ACTION ITEM — Phase 1 Architecture Addendum**  

| Must replicate the new event-based preprocessing exactly When P2-M2 (RecordEncoder) is built, it MUST replicate the event-based preprocessing used in the redesigned P1-M3 exactly: per-metric z-scoring and the metric\_name vocabulary. Source these from the SAME global vocab maps and per-metric value stats used in training — never re-derive them independently at inference time. The Implementation Steps and AI Prompt Brief below have been updated accordingly; use Section 7 (P1-M3) of the Phase 1 Architecture Update Addendum as the source of truth before Member B starts this module. |
| :---- |

**Overview:** Transform raw event records into model-ready tensor representations. Categorical fields (cloud, entity\_type, namespace, metric\_name) → Embedding Table lookup; the single value\_norm numeric field → per-metric z-score (NOT LayerNorm — must match training exactly); Timestamps → Time2Vec (k=8). Output: Record Embeddings of shape (batch, seq\_len, feature\_dim).

**Tech Stack:** Python, PyTorch

**Depends On:** P1-M6 (feature metadata for embedding tables and per-metric value stats), P2-M1 (event batches)

### **Revised Implementation Steps:**

* Load the categorical vocabulary (4 fields, incl. metric\_name) and per-metric\_name value stats (mean, std) from P1-M6 feature metadata — the SAME global maps computed by compute\_vocab\_sizes() / compute\_metric\_value\_stats() during training

* Implement CategoricalEncoder: map string fields (cloud, entity\_type, namespace, metric\_name) to int IDs using vocabulary, then lookup in nn.Embedding table

* Implement NumericalEncoder: z-score the single value\_norm reading using the per-metric\_name (mean, std) loaded above, floored by AUG\_VALUE\_NORM\_EPS — do NOT apply a generic LayerNorm across 6 fixed metrics, that assumption no longer holds

* Assemble RecordEncoder: concatenate all encoded fields, pass through Time2Vec, return (batch, seq\_len, 256\)

* Handle OOV (out-of-vocabulary) op\_ids and metric\_names gracefully: map to a dedicated \<UNK\> token ID

### **Integration with the Rest of the System:**

RecordEncoder must use the SAME embedding tables and per-metric value stats as used during training (loaded from P1-M6 registry). Output tensor shape (batch, seq\_len, feature\_dim) is the input to the TSTCC encoder in P2-M3. Mismatches here will silently corrupt all embeddings — this risk is now higher than originally planned because per-metric z-scoring, unlike a single global scaler, requires exactly the right vocabulary keyed by metric\_name.

### **Revised AI Prompt Brief for Implementation:**

*Implement a production RecordEncoder for cloud telemetry records. Must replicate the exact event-based preprocessing used during the redesigned TSTCC training: (1) CategoricalEncoder: loads cloud, entity\_type, namespace, metric\_name vocabularies from feature\_meta.json; maps string → int; uses nn.Embedding (same embedding\_dim as training); handles OOV with UNK token, (2) NumericalEncoder: z-scores the single value\_norm reading per metric\_name using precomputed (mean, std) pairs loaded from feature\_meta.json (NOT a generic LayerNorm — this must match compute\_metric\_value\_stats() exactly), (3) Time2Vec: load pre-trained Time2Vec parameters from registry; encode timestamps as (linear\_term, sin\_1..sin\_7), (4) Assemble and concatenate all parts into (batch, seq\_len, 256\) tensor. Load all params from ArtifactBundle at init time — never re-derive vocab or value stats independently at inference.*

### **What to Watch Out For:**

* OOV entity\_ids and metric\_names at inference time are common for new cloud resources — critical to handle gracefully, not crash

* Time2Vec parameters MUST be loaded from the registry, not reinitialized — a fresh init will corrupt all embeddings

* **\[NEW\]** Per-metric z-scoring means a missing or mismatched metric\_name in the vocab silently produces a wrong scale for that reading — validate the metric\_name vocab loaded here matches the one used in P1-M3 training byte-for-byte.

* **\[NEW\]** Do not reuse the old LayerNorm-based NumericalEncoder design from the original plan — it assumed 6 fixed, comparable-scale metrics, which no longer holds.

## **P2-M3 — Retrieved Encoder (Inference)**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member C, Detection & Alerting Lead. Sprint Week: Week 1\. Priority: HIGH.*

**Overview:** Load the trained TSTCC encoder in inference mode for generating current-record embeddings. This is the same architecture as P1-M3 but frozen and in eval() mode.

**Tech Stack:** PyTorch

**Depends On:** P1-M6 (encoder weights .pt), P2-M2 (record embeddings as input)

### **Implementation Steps:**

* Implement EncoderInference wrapper that loads the .pt weights from ArtifactBundle

* Set model to eval() and disable gradient computation (torch.no\_grad())

* Expose encode(record\_embeddings) → sequence\_embedding (batch, 128\)

* Add batch processing with configurable chunk\_size to avoid OOM on large batches

* Implement warm-up: run 1 dummy batch on startup to pre-load CUDA kernels

* Add latency logging: track P50/P95/P99 encoding latency per batch

### **Integration with the Rest of the System:**

Takes output of P2-M2 (record embeddings). Outputs sequence embeddings (batch, 128\) that feed into P2-M5 (Current Embedding computation) and are compared against P2-M4 (Reference Encoder output). Both P2-M3 and P2-M4 use the same encoder weights — they differ only in which input they receive.

### **AI Prompt Brief for Implementation:**

*Implement an EncoderInference class that wraps the TSTCC encoder for production inference. Requirements: (1) Load encoder weights from ArtifactBundle.load\_latest(), strip the ProjectionHead (inference uses backbone only), (2) Set model.eval() and wrap all forward passes in torch.no\_grad(), (3) Method encode(tensor: Tensor) → Tensor: handles batching internally with chunk\_size=64 to prevent OOM, returns (N, 128\) float32 embeddings, (4) Method encode\_single(tensor) → Tensor: for single-record path (N=1), (5) Latency tracking: log P50/P95 ms per batch to a LatencyStats object, (6) Startup warm-up: run 3 dummy batches of zeros on \_\_init\_\_ to pre-compile CUDA ops.*

### **What to Watch Out For:**

* Forgetting to strip the projection head means embeddings are from the wrong space — validate shape is (batch, 128\) not (batch, 256\)

* CUDA vs CPU: for small batches (\<16 records) at inference time, CPU may actually be faster than GPU due to kernel launch overhead

* If the model weights file is missing or corrupt, the entire inference pipeline halts — add a clear startup health check

## **P2-M4 — Pretrained Encoder (Reference)**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member C, Detection & Alerting Lead. Sprint Week: Week 1\. Priority: HIGH.*

**Overview:** Load the same TSTCC encoder as a reference model that encodes historical anchor records for comparison. Used to compute reference-point embeddings that are stored in the Dynamic Entity Store.

**Tech Stack:** PyTorch

**Depends On:** P1-M6 (encoder weights .pt), P2-M2 (historical record embeddings as input)

### **Implementation Steps:**

* Reuse EncoderInference from P2-M3 — this is the same model class, different usage context

* Implement ReferenceEncoderService: on startup, encode the last 90 days of historical records per entity

* Output per-entity centroid: mean of last N embeddings (N=30 by default, configurable)

* Store per-entity statistics: variance of last N embeddings (measure of behavioral spread)

* Schedule periodic refresh: re-encode new historical data every 24h and update centroid

* Write to Dynamic Entity Store (P2-M6) via EntityStoreWriter interface

### **Integration with the Rest of the System:**

The reference embeddings and centroids computed here are the primary inputs to P2-M7 (Cosine Distance). Coordinate with Member B on the EntityStoreWriter interface before implementing, since P2-M6 owns the store schema.

### **AI Prompt Brief for Implementation:**

*Implement a ReferenceEncoderService using the TSTCC encoder. This service encodes historical records to build per-entity behavioral baselines: (1) Load encoder from ArtifactBundle, (2) For each entity\_id, retrieve the last 90 days of records from the historical store, encode them in batches, (3) Compute per-entity centroid: mean of the last N=30 embedding vectors, (4) Compute per-entity variance: trace of the covariance matrix of last N embeddings (scalar measure of behavioral spread), (5) Write centroid, variance, and last\_N\_embeddings list to the EntityStore via EntityStoreWriter interface, (6) Support incremental update: given new records for an entity, update centroid with EMA (alpha=0.1) without re-encoding all history.*

### **What to Watch Out For:**

* Initial cold start — new entity\_ids have no history. Implement a fallback: use global average centroid for first 24h

* EMA centroid update can drift if new behavior is very different — add a drift alarm: if new embedding distance from centroid \> 3 std deviations, flag the entity

* Memory: keeping last\_N\_embeddings for 100K entities × 128-d × 30 records \= \~1.5 GB RAM — use float16 storage in Redis

## **P2-M5 — Current Embedding**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member B, Inference & Storage Lead. Sprint Week: Week 2\. Priority: CRITICAL.*

**Overview:** Aggregate the sequence embedding output from the TSTCC encoder into a single current-record embedding vector (d=128) per entity. This is the 'current behavior fingerprint' that is compared against the entity's historical baseline.

**Tech Stack:** NumPy

**Depends On:** P2-M3 (Inference Encoder output)

### **Implementation Steps:**

* Receive (batch, 128\) output from P2-M3

* Group embeddings by entity\_id within the batch

* For multi-record entities in a batch: compute mean pooling as the current embedding

* Normalize to unit L2 norm (F.normalize or np.linalg.norm)

* Attach metadata: entity\_id, batch\_timestamp, record\_count, cloud\_provider

* Return list of CurrentEmbedding objects for the batch

### **Integration with the Rest of the System:**

CurrentEmbedding objects are written to the Dynamic Entity Store (P2-M6) as the 'current\_embedding' field. They are also directly consumed by P2-M7 (Cosine Distance) for comparison against the centroid. This module is lightweight — avoid adding heavy logic here.

### **AI Prompt Brief for Implementation:**

*Implement a CurrentEmbeddingAggregator. Input: list of (entity\_id, embedding\_128d) pairs from the inference encoder. For each unique entity\_id, mean-pool all its embeddings in the current batch, L2-normalize the result, and return a CurrentEmbedding dataclass with fields: entity\_id (str), embedding (np.ndarray shape 128), batch\_timestamp (datetime), record\_count (int), cloud\_provider (str). Handle edge case: entity appears only once in batch (return that single embedding, normalized). Output: List\[CurrentEmbedding\] ready for writing to the entity store.*

### **What to Watch Out For:**

* If batch\_size is very small, some entities may have only 1 record — mean pooling over 1 vector is fine, but log record\_count for monitoring

* Ensure L2 normalization happens AFTER mean pooling, not before — order matters for mean pooling in hyperspherical space

## **P2-M6 — Dynamic Entity Store**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member B, Inference & Storage Lead. Sprint Week: Week 3\. Priority: CRITICAL.*

**Overview:** The central per-entity state store. Holds: current\_embedding, centroid\_EMA, last\_N\_embeddings (rolling window of 30), and stats (var, count, last\_update) per entity. Redis for fast read/write; PostgreSQL+PGVector for analytical queries.

**Tech Stack:** Redis / DynamoDB / PostgreSQL \+ PGVector

**Depends On:** P2-M4 (reference embeddings written on startup), P2-M5 (current embeddings written per batch)

### **Implementation Steps:**

* Design Redis key schema: entity:{entity\_id}:current → JSON blob; entity:{entity\_id}:centroid → float16 bytes; entity:{entity\_id}:history → Redis List of last 30 embeddings

* Implement EntityStoreWriter: write\_current(entity\_id, embedding), update\_centroid(entity\_id, new\_embedding, alpha=0.1)

* Implement EntityStoreReader: get\_centroid(entity\_id), get\_history(entity\_id, n=30), get\_stats(entity\_id)

* Implement history rotation: LPUSH new embedding, LTRIM to keep last 30 (Redis native ops)

* Add PostgreSQL+PGVector as secondary store for batch analytics queries (e.g., find all entities with high variance)

* Write EntityStoreClient that abstracts Redis and PGVector behind a unified interface

### **Integration with the Rest of the System:**

P2-M7 (Cosine Distance) and P2-M8 (MMD Monitor) read from this store. P2-M9 (Retrieved Episodes) also reads the history list. The store schema is the contract between multiple modules — define and document it in shared/entity\_store\_schema.py before other modules integrate.

### **AI Prompt Brief for Implementation:**

*Implement a DynamicEntityStore using Redis as the primary backend. Schema per entity: (1) current\_embedding: float16 bytes (128 values), (2) centroid\_ema: float16 bytes updated via EMA, (3) history\_embeddings: Redis List of up to 30 recent embeddings as float16 bytes, (4) stats: Redis Hash with fields last\_update\_ts (ISO str), record\_count (int), embedding\_variance (float). Implement EntityStoreWriter and EntityStoreReader classes. History rotation: use LPUSH \+ LTRIM to keep last 30 entries atomically. Also add a secondary PostgreSQL+PGVector table for analytical lookups with pgvector extension. Include async read methods (aioredis) for high-throughput inference.*

### **What to Watch Out For:**

* Redis memory: 100K entities × (128 × 2 bytes × 32 embeddings) ≈ 800 MB. Set maxmemory-policy \= allkeys-lru

* Redis List LTRIM is not atomic with LPUSH by default — use Redis MULTI/EXEC transaction for history rotation

* PGVector indexing (ivfflat) is slow for large updates — only index batch-write jobs, not per-record writes

## **P2-M7 — Cosine Distance**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member B, Inference & Storage Lead. Sprint Week: Week 3\. Priority: CRITICAL.*

**Overview:** Compute two deviation scores: Global Deviation Score (current embedding vs. global centroid) and Local Deviation Score (current embedding vs. local window of 30 embeddings). Both are cosine distances normalized to \[0,1\].

**Tech Stack:** NumPy, Scikit-learn

**Depends On:** P2-M5 (current embedding), P2-M6 (centroid and history)

### **Implementation Steps:**

* Implement cosine\_distance(a, b): \= 1 \- dot(a,b) / (|a|\*|b|). Since embeddings are L2-normalized, this simplifies to 1 \- dot(a,b)

* Global Deviation: cosine\_distance(current\_embedding, entity\_centroid) → scalar \[0,1\]

* Local Deviation: mean of cosine\_distance(current\_embedding, e\_i) for e\_i in last 30 embeddings → scalar \[0,1\]

* Return DeviationScore dataclass: entity\_id, global\_score, local\_score, timestamp

* Add threshold-based flags: global\_flag \= (global\_score \> GLOBAL\_THRESHOLD), local\_flag \= (local\_score \> LOCAL\_THRESHOLD)

* Write unit tests: identical embeddings → score=0; orthogonal embeddings → score=1

### **Integration with the Rest of the System:**

DeviationScore is one of three inputs to P2-M10 (Final Anomaly Score). The formula is: Final \= 0.4\*Deviation \+ 0.4\*Drift \+ 0.2\*(1-Similarity). Deviation here is max(global\_score, local\_score). Pass DeviationScore to P2-M10 via the ScoringInput dataclass.

### **AI Prompt Brief for Implementation:**

*Implement a CosineDeviationScorer. Input: CurrentEmbedding (128-d L2-normalized numpy array) and entity profile from EntityStore (centroid 128-d, history list of up to 30 × 128-d embeddings). Output: DeviationScore dataclass with entity\_id, global\_deviation (float 0–1), local\_deviation (float 0–1), global\_flag (bool), local\_flag (bool). Since embeddings are L2-normalized, use the fast formula: cos\_dist \= 1 \- np.dot(a, b). For local: vectorized computation — stack history into matrix (30, 128), compute all dot products at once via matrix multiply, mean the distances. Thresholds: global \> 0.3 → flag, local \> 0.25 → flag. Include NumPy-only implementation (no sklearn dependency in hot path).*

### **What to Watch Out For:**

* New entities with no centroid — return global\_deviation=0.5, local\_deviation=0.5 as defaults, set a cold\_start flag

* History list may have \< 30 entries for newer entities — handle variable-length history gracefully

## **P2-M8 — MMD Drift Monitor**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member B, Inference & Storage Lead. Sprint Week: Week 4\. Priority: HIGH.*

**Overview:** Detect behavioral drift using Maximum Mean Discrepancy (MMD) with an RBF kernel. Compares the distribution of past 90 days of embeddings vs. recent 30 days. Outputs a drift score \[0,1\] and a drift flag.

**Tech Stack:** PyOD, SciPy, NumPy

**Depends On:** P2-M6 (history embeddings — past 90 days vs recent 30 days)

### **Implementation Steps:**

* Implement mmd\_rbf(X, Y, sigma=1.0): compute MMD² \= E\[k(x,x')\] \+ E\[k(y,y')\] \- 2E\[k(x,y)\]

* Load past-90-days embeddings and recent-30-days embeddings per entity from P2-M6

* Compute MMD score and scale to \[0,1\] using empirical calibration (99th percentile of null distribution)

* Set drift\_flag \= True if drift\_score \> 0.5

* Run MMD computation in a background thread/process (not on the hot inference path)

* Cache drift scores per entity with 30-minute TTL in Redis

### **Integration with the Rest of the System:**

Drift score is the second input to P2-M10 (Final Anomaly Score). Since MMD is expensive, cache results and run asynchronously. Provide DriftScore(entity\_id, drift\_score, drift\_flag, computed\_at) dataclass. P2-M10 reads the latest cached drift score — design for possible staleness (drift score may be up to 30 min old).

### **AI Prompt Brief for Implementation:**

*Implement an MMDDriftMonitor for behavioral drift detection. (1) MMD computation: mmd\_rbf(X: ndarray (N,128), Y: ndarray (M,128), sigma=1.0) using unbiased MMD² estimator with RBF kernel k(x,y)=exp(-||x-y||²/(2σ²)). Implement the efficient O(N²) estimator using matrix operations. (2) DriftMonitor class: loads past-90-day and recent-30-day embedding lists from EntityStore, computes MMD, scales score using per-entity empirical 99th percentile, returns DriftScore dataclass. (3) AsyncDriftWorker: runs MMD computation in a ThreadPoolExecutor, caches results in Redis with 30-min TTL. (4) Null distribution calibration: on first run, compute MMD on 1000 random same-distribution pairs to calibrate the 0–1 scaling.*

### **What to Watch Out For:**

* MMD is O(N²) — for N=90-day history (90×24×60/entity\_rate records), this can be very large. Subsample to 200 max per distribution

* Sigma (RBF bandwidth) must be calibrated to the embedding space — use median heuristic: sigma \= median(pairwise distances) / sqrt(2)

* Don't run MMD on the hot inference path — this module MUST be async

## **P2-M9 — Retrieved Similar Episodes**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member C, Detection & Alerting Lead. Sprint Week: Week 2\. Priority: HIGH.*

**Overview:** Given the current embedding of an entity, retrieve the Top-K most similar historical episodes from the FAISS index. Returns similarity scores and metadata (incident IDs, timestamps, severities) of similar past events.

**Tech Stack:** FAISS / ScaNN

**Depends On:** P1-M5 (FAISS index), P2-M5 (current embedding as query)

### **Implementation Steps:**

* Load FAISS index from ArtifactBundle (P1-M6) on service startup

* Implement EpisodeRetriever.search(query\_embedding, k=10): FAISS IndexFlatL2 or IVF search

* Convert L2 distance to cosine similarity (since embeddings are L2-normalized: cosine\_sim \= 1 \- L2\_dist²/2)

* Return EpisodeSearchResult: list of (similarity\_score, incident\_id, entity\_id, timestamp, cloud\_provider, severity\_label)

* Filter results: exclude episodes from the querying entity itself (prevent self-retrieval bias)

* Cache query results with entity\_id \+ embedding hash as cache key (30-minute TTL)

### **Integration with the Rest of the System:**

Similarity score (average of top-K) is the third input to P2-M10 Final Anomaly Score: Final \= 0.4\*Dev \+ 0.4\*Drift \+ 0.2\*(1-Similarity). Similar episode metadata is included in P2-M14 (Explainable Alert) as 'similar\_incidents' field. Share the EpisodeSearchResult dataclass with Member C who owns P2-M14.

### **AI Prompt Brief for Implementation:**

*Implement an EpisodeRetriever for similar incident lookup using FAISS. (1) Load FAISS IndexIVFFlat from the ArtifactBundle on startup, load episode metadata (episode\_id, entity\_id, timestamp, cloud\_provider, severity) from a parquet metadata file, (2) Method search(query\_emb: ndarray (128,), k=10, exclude\_entity\_id=None): run FAISS kNN search, convert L2 distances to cosine similarities (sim \= 1 \- dist²/2 for normalized vectors), filter self-retrieval, return top-k as List\[EpisodeSearchResult\], (3) Method batch\_search(query\_embs: ndarray (N,128), k=10): vectorized batch search for throughput, (4) Add Redis caching with key=f'episode:{entity\_id}:{embedding\_hash\[:8\]}' and TTL=1800s.*

### **What to Watch Out For:**

* FAISS IVF search has a nprobe parameter — too low (default=1) gives poor recall. Set nprobe=20 minimum

* Self-retrieval bias: a training entity will always find itself as the top match — exclude\_entity\_id filter is critical

* FAISS index can be hundreds of MB — load into memory once at startup, not per-request

## **P2-M10 — Final Anomaly Score**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member C, Detection & Alerting Lead. Sprint Week: Week 3\. Priority: CRITICAL.*

**Overview:** Compute the final anomaly score as a weighted combination: Score \= 0.4\*Deviation \+ 0.4\*Drift \+ 0.2\*(1-Similarity). Map the score to severity levels: Low/Medium/High/Critical.

**Tech Stack:** NumPy

**Depends On:** P2-M7 (deviation), P2-M8 (drift), P2-M9 (similarity)

### **Implementation Steps:**

* Define ScoringInput dataclass: deviation\_score, drift\_score, similarity\_score, entity\_id, batch\_ts

* Implement AnomalyScorer.score(ScoringInput) → AnomalyResult

* Apply formula: final \= 0.4\*deviation \+ 0.4\*drift \+ 0.2\*(1 \- similarity)

* Map to severity: \<0.3=Low, 0.3–0.6=Medium, 0.6–0.8=High, \>0.8=Critical

* Add per-component breakdown to AnomalyResult for explainability

* Write unit tests: all zeros → 0.2 (from 1-similarity=1); all ones → 1.0; balanced case

### **Integration with the Rest of the System:**

AnomalyResult feeds into P2-M11 (Deduplication). If the result passes deduplication, it goes to P2-M12 (Correlation Engine) and eventually P2-M14 (Explainable Alert). AnomalyResult must carry all three component scores for the alert explanation.

### **AI Prompt Brief for Implementation:**

*Implement an AnomalyScorer with the formula: final\_score \= 0.4\*deviation\_score \+ 0.4\*drift\_score \+ 0.2\*(1 \- similarity\_score), where all inputs are in \[0,1\]. (1) ScoringInput dataclass: entity\_id, deviation\_score, drift\_score, similarity\_score, component\_scores (dict), batch\_timestamp, (2) AnomalyResult dataclass: entity\_id, final\_score, severity (Enum: LOW/MEDIUM/HIGH/CRITICAL), deviation\_contribution, drift\_contribution, similarity\_contribution, batch\_timestamp, (3) SeverityMapper: \<0.3→LOW, 0.3-0.6→MEDIUM, 0.6-0.8→HIGH, \>0.8→CRITICAL with configurable thresholds from YAML, (4) Handle missing inputs: if drift\_score is stale (MMD async), use the last valid score. If no similarity (new entity), substitute 0 (worst case — maximizes score component).*

### **What to Watch Out For:**

* Drift score staleness: MMD runs async with 30-min TTL. The scorer must handle None drift\_score gracefully (use fallback=0.5)

* Similarity for new entities is undefined — defaulting to 0 (similarity=0 → 1-0=1 → adds full 0.2 penalty) is the safe choice

* Weight tuning (0.4/0.4/0.2) is empirical — document these as configurable constants in config.yaml, not hardcoded

## **P2-M11 — Deduplication**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member C, Detection & Alerting Lead. Sprint Week: Week 1\. Priority: MEDIUM.*

**Overview:** Prevent alert storms by deduplicating anomaly results within a 5-minute time window per entity. Uses MinHash or SimHash for near-duplicate detection. Outputs: is\_duplicate (bool) and canonical\_incident\_id.

**Tech Stack:** Redis, NumPy

**Depends On:** P2-M10 (AnomalyResult)

### **Implementation Steps:**

* Implement MinHashDeduplicator: hash (entity\_id \+ severity \+ top\_3\_features) → 64-bit fingerprint

* Check Redis for existing fingerprint within 5-minute window: key \= dedup:{entity\_id}:{window\_bucket}

* If fingerprint exists and similarity \> 0.9 → is\_duplicate=True, return canonical\_incident\_id

* If not duplicate → store fingerprint in Redis with 5-minute TTL, assign new canonical\_incident\_id

* Return DedupResult: is\_duplicate, canonical\_incident\_id, first\_seen\_ts, recurrence\_count

* Increment recurrence\_count for deduped alerts (useful for correlation engine)

### **Integration with the Rest of the System:**

DedupResult wraps the AnomalyResult and passes to P2-M12 (Correlation Engine). Duplicate alerts are suppressed from the alert delivery path (P2-M14) but their recurrence\_count is incremented. This is a lightweight module — build it early in Week 1 as it's required before end-to-end testing.

### **AI Prompt Brief for Implementation:**

*Implement an alert deduplication layer using Redis. (1) Fingerprinting: generate a 64-bit hash from (entity\_id, severity\_level, top\_features\_sorted\_tuple, cloud\_provider) using hashlib or mmh3, (2) Time-windowed dedup: bucket timestamp to 5-minute intervals (ts // 300 \* 300), Redis key: dedup:{entity\_id}:{bucket}, value: canonical\_incident\_id, TTL: 300s, (3) DedupChecker.check(AnomalyResult) → DedupResult: if key exists, is\_duplicate=True and increment recurrence\_count with HINCRBY, else create new incident\_id (UUID4), store in Redis, is\_duplicate=False, (4) Return DedupResult: is\_duplicate, canonical\_incident\_id, recurrence\_count, first\_seen\_ts.*

### **What to Watch Out For:**

* 5-minute window is configurable per entity criticality — critical entities may need shorter dedup windows (1 min)

* Redis key TTL must match the dedup window exactly — a mismatch causes either missed dedup or eternal suppression

## **P2-M12 — Correlation Engine**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member C, Detection & Alerting Lead. Sprint Week: Week 3\. Priority: MEDIUM.*

**Overview:** Group related alerts into correlated incident groups using an entity-attribute graph. Detects community structures (service-wide outage vs. single entity anomaly) and assigns correlated\_incident\_group\_id.

**Tech Stack:** NetworkX / Neo4j

**Depends On:** P2-M11 (DedupResult with canonical incident IDs)

### **Implementation Steps:**

* Build entity-attribute graph: nodes \= entity\_ids, edges \= shared attributes (same region, same op\_id, same cloud\_provider)

* On new alert arrival, add it to the graph and run community detection (Louvain or label propagation via NetworkX)

* Assign correlated\_incident\_group\_id \= community\_id if community size \> 2, else standalone\_group

* Detect incident grouping patterns: if 10+ entities in same region alert within 60s → region-wide incident

* Produce CorrelationResult: incident\_group\_id, related\_incident\_ids, community\_size, group\_type (single/regional/global)

* Store correlation graph in Neo4j for visualization and historical querying (optional for capstone)

### **Integration with the Rest of the System:**

CorrelationResult is input to P2-M13 (Escalation Engine) — group\_type and community\_size influence escalation severity. Related incident IDs are included in P2-M14 alert payload as 'related\_incidents' field.

### **AI Prompt Brief for Implementation:**

*Implement a CorrelationEngine for grouping related alerts. Use NetworkX for graph operations: (1) AlertGraph: maintains a directed graph where nodes are entity\_ids with attributes (cloud\_provider, region, op\_id) and edges are drawn between entities that share ≥2 attributes, (2) On each new alert, add the entity to the graph, draw edges to entities that had alerts in the last 10 minutes (time-windowed), run nx.community.louvain\_communities() or connected\_components(), (3) CorrelationResult dataclass: entity\_id, incident\_group\_id, related\_entity\_ids, group\_size, group\_type (ISOLATED/CORRELATED/REGIONAL\_OUTAGE), (4) Regional outage trigger: if group\_size \> 10 and all entities share the same region → group\_type=REGIONAL\_OUTAGE. Prune graph: remove nodes with no alerts in last 30 minutes.*

### **What to Watch Out For:**

* NetworkX community detection is slow for large graphs (\>10K nodes) — prune aggressively to recent alerts only

* Neo4j is optional for the capstone demo — implement NetworkX version first, make Neo4j an optional backend

* Louvain is non-deterministic — set random\_state for reproducibility in tests

## **P2-M13 — Escalation Engine**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member C, Detection & Alerting Lead. Sprint Week: Week 4\. Priority: HIGH.*

**Overview:** Determine the escalation level (Sev1/Sev2/Sev3/Sev4) and target team / on-call assignment based on: entity criticality, severity score, business hours, correlation group type, and organizational policies.

**Tech Stack:** Python / Rules Engine

**Depends On:** P2-M12 (CorrelationResult — group\_type and severity)

### **Implementation Steps:**

* Define escalation rules in YAML: {entity\_criticality: critical, min\_severity: HIGH, group\_type: REGIONAL\_OUTAGE} → Sev1 → on\_call\_team: SRE

* Implement RulesEngine that evaluates YAML rules in priority order (first match wins)

* Add business hours check: P1 alerts always page; P2/P3 alerts respect quiet hours (00:00–07:00 local)

* Implement on-call assignment: load on-call schedule from PagerDuty API or static YAML schedule

* Output EscalationResult: severity\_level (Sev1-4), escalation\_team, notify\_method (page/email/slack), policy\_applied

* Add suppression: if entity was Sev3 within last 4h from same group → downgrade to Sev4 notification only

### **Integration with the Rest of the System:**

EscalationResult feeds directly into P2-M14 (Explainable Alert) which delivers the actual notification. The YAML rules config must be version-controlled in the repo as escalation\_rules.yaml.

### **AI Prompt Brief for Implementation:**

*Implement an EscalationEngine using a YAML rules file. (1) Rules format: each rule has conditions (entity\_criticality, min\_final\_score, group\_type, business\_hours) and actions (severity\_level, target\_team, notify\_method). Evaluate rules in order, first match wins, (2) BusinessHoursChecker: given timezone from entity metadata, return is\_business\_hours bool, (3) SeverityMapper: combine anomaly severity (LOW/MED/HIGH/CRITICAL) with correlation group\_type (ISOLATED/CORRELATED/REGIONAL) to produce Sev1-4: CRITICAL+REGIONAL=Sev1, CRITICAL+ISOLATED=Sev2, HIGH+CORRELATED=Sev2, HIGH+ISOLATED=Sev3, else Sev4, (4) EscalationResult: entity\_id, sev\_level, target\_team, notify\_method (PagerDuty/Slack/Email), policy\_name\_applied, business\_hours\_flag.*

### **What to Watch Out For:**

* Business hours timezone handling — always store timezones as IANA strings (America/New\_York, not UTC-5)

* PagerDuty API integration is a bonus — implement static YAML on-call schedule first for the demo

## **P2-M14 — Explainable Alert API**

*Unaffected by the redesign. Phase 2 – Inference (Online). Owner: Member C, Detection & Alerting Lead. Sprint Week: Week 4\. Priority: CRITICAL.*

**Overview:** Build the final alert delivery API. Assembles the complete alert payload (JSON) with full explainability: final score, severity, per-component breakdown, similar past incidents, contributors, timestamp. Delivers via Email/Slack/PagerDuty/SIEM/Dashboard.

**Tech Stack:** FastAPI / Flask, JSON

**Depends On:** P2-M13 (EscalationResult), P2-M10 (component scores), P2-M9 (similar episodes), P2-M12 (related incidents)

### **Implementation Steps:**

* Design AlertPayload JSON schema: {alert\_id, entity\_id, timestamp, final\_score, severity, deviation\_score, drift\_score, similarity\_score, similar\_incidents\[\], related\_incidents\[\], contributing\_features\[\], escalation\_team, sev\_level, cloud\_provider, region}

* Build FastAPI app with POST /alert endpoint that accepts AlertPayload and dispatches it

* Implement SlackNotifier: send formatted block kit message to webhook URL

* Implement EmailNotifier: send HTML email via SMTP with alert details table

* Implement PagerDutyNotifier: POST to PagerDuty Events API v2

* Implement DashboardWriter: write alert to a time-series store (InfluxDB or PostgreSQL) for dashboard visualization

* Add WebSocket endpoint: /alerts/stream for real-time dashboard feed

### **Integration with the Rest of the System:**

This is the terminal module — it consumes from all upstream modules. Build the FastAPI server so it can be run standalone (for testing) by accepting AlertPayload JSON directly. The WebSocket stream is the dashboard feed. Write a simple HTML dashboard (index.html) that connects to the WebSocket and displays alerts in real-time.

### **AI Prompt Brief for Implementation:**

*Build an Explainable Alert API using FastAPI. (1) AlertPayload Pydantic model: alert\_id (UUID), entity\_id, timestamp (datetime), final\_score (float), severity (Enum Sev1-4), deviation\_score, drift\_score, similarity\_score, component\_breakdown (dict), similar\_incidents (List\[EpisodeSummary\]), related\_incidents (List\[str\]), contributing\_features (List\[str\]), escalation\_team (str), cloud\_provider (str), region (str), (2) POST /alert: validates payload, dispatches to enabled notifiers in parallel (asyncio.gather), returns dispatch\_status per channel, (3) SlackNotifier: formats a Slack Block Kit message with score breakdown, (4) GET /alerts/recent: returns last 100 alerts from Redis sorted set, (5) WebSocket /alerts/stream: pushes new alerts to connected clients, (6) Simple HTML dashboard page served at / showing live alert feed.*

### **What to Watch Out For:**

* Alert delivery failures (Slack down, SMTP error) must not block the pipeline — use asyncio gather with return\_exceptions=True

* Rate limiting: Slack has 1 message/second per webhook — implement a notifier queue with rate limiting

* The WebSocket dashboard is a capstone bonus — implement it after all delivery channels work

# **7\. Risk Register & Watch Points**

These are the highest-risk areas that can delay the project if not addressed early. Monitor these at the start of each week in the team standup.

| Risk | Likelihood | Description | Mitigation |
| :---- | :---- | :---- | :---- |
| Training Data Volume | HIGH | 1-month of minute-wise multi-cloud records can be 10–50GB. Slow to load, slow to augment, slow to train. | Use chunked loading from the start. Develop on 1-day sample first. Only run full training in final week. |
| Timestamp Format Mismatch | HIGH | Two timestamp formats coexist in the schema (+00:00 ms precision vs Z with microseconds). Inconsistency silently corrupts Time2Vec. | Enforce UTC normalization in P1-M1 before any downstream processing. Add assertion in schema validator. |
| Feature Metadata Drift | HIGH | Vocabulary mappings (op\_id→int, entity→int, and now metric\_name→int) used at training time MUST be identical at inference time. Any mismatch silently corrupts all embeddings. | Version-lock feature\_meta.json with the model checkpoint in P1-M6. Never regenerate it separately. |
| FAISS Index Memory | MEDIUM | FAISS IndexIVFFlat for 5M+ records can use 3–5 GB RAM. Will OOM on standard capstone machines. | Start with IndexFlatL2 for \<500K records. Use IndexIVFPQ with m=8, nbits=8 for larger corpora. |
| Redis Memory | MEDIUM | 100K entities × 30 history embeddings × 128 dims × 2 bytes (float16) ≈ 800 MB RAM in Redis. | Store embeddings as float16 bytes. Set maxmemory-policy allkeys-lru. For demo, reduce to 10K entities. |
| MMD Computation Cost | MEDIUM | MMD is O(N²) per entity. Running it per batch on the hot inference path will block everything. | AsyncDriftWorker MUST run in a background thread. Results are cached with 30-min TTL. Final scorer handles stale values. |
| Integration Contracts | HIGH | Shared dataclasses (BatchEvent, CurrentEmbedding, DeviationScore, AnomalyResult) evolve during development causing import errors when merging. | Define and freeze all dataclasses in shared/types.py in Week 1\. Any change requires team review and a PR with migration notes. |
| Cold Start (New Entities) | MEDIUM | New entity\_ids not seen in training have no centroid, no history, no FAISS entries. All scoring modules must handle this gracefully. | Define cold-start defaults globally: centroid=global\_mean, history=empty, deviation=0.5, drift=0.5, similarity=0. |

## **Additions from the Phase 1 Architecture Update Addendum**

  **UPDATED — Phase 1 Architecture Addendum**  

Both risks below were discovered and resolved during Phase 1 implementation — they were not anticipated in the original register and are added here for future modules' awareness.

| Risk | Likelihood | Description | Resolution |
| :---- | :---- | :---- | :---- |
| Metric Schema Heterogeneity | REALIZED | No universal metric schema exists across resource types (VM vs. Storage vs. other services each emit disjoint metric sets). The original fixed-6-metric assumption broke on real data — an Azure Storage account emits an entirely different metric set (Availability, Egress, Transactions, SuccessE2ELatency, VolumeQueueLength…) with no overlap with VM metrics. | Redesigned to an event-based schema: metric\_name as a 4th categorical embedding (learned, not hardcoded), single z-scored value\_norm feature. See Directory Structure Addendum Sections 1 and 5\. |
| Windows Multiprocessing Pickling | REALIZED | DataLoader(num\_workers\>0) on Windows uses 'spawn', which pickles the entire Dataset object. pyarrow.parquet.ParquetFile cannot be pickled (non-trivial \_\_cinit\_\_), crashing any worker-based training on Windows dev machines. | StreamingAugPairsDataset no longer stores an open ParquetFile on self; each process lazily opens its own handle on first use, after spawning completes. |

# **8\. Integration Checklist**

*Unchanged.*

Use this checklist at the end of each week to verify integration across module boundaries. Each item should be checked off (and the test committed) before closing the week's milestone.

## **Week 1 Integration Gates**

* shared/types.py is committed with: BatchEvent, CurrentEmbedding, DeviationScore, AnomalyResult, EpisodeSearchResult, DedupResult, CorrelationResult, EscalationResult — all team members have reviewed and agreed on field names

* P1-M1 CorpusIterator yields dicts with the exact field names defined in shared/types.py schema

* P1-M2 StreamingAugPairsDataset accepts CorpusIterator-derived aug\_pairs.parquet and yields (view\_a, view\_b) window pairs of shape (batch, seq\_len, feature\_dim)

* P2-M3/M4 model loaders can load a dummy checkpoint without import errors on all 3 team members' machines

* Docker-compose up brings Redis, Kafka, PostgreSQL online with no errors

## **Week 2 Integration Gates**

* P1-M3 encoder forward pass produces output of shape (batch, 128\) — verify with assert statement in test

* P1-M4 training loop runs 10 batches without NaN loss — run: python \-m phase1.train.train\_tstcc \--epochs 1 \--fast-debug

* P2-M1 Kafka consumer receives 100 synthetic test events from a producer script

* P2-M5 CurrentEmbeddingAggregator accepts output from P2-M3 and returns List\[CurrentEmbedding\]

* P2-M9 FAISS search returns top-10 results for a random query embedding (even on dummy index)

## **Week 3 Integration Gates**

* P1-M5 FAISS index built from trained encoder — spot check: query an entity's own record, it should be the \#1 nearest neighbor

* P1-M6 ArtifactBundle.load\_latest() returns a working encoder and FAISS index without manual path configuration

* P2-M6 EntityStore write-then-read round trip: write a CurrentEmbedding, read it back, values match (within float16 precision)

* P2-M7 DeviationScore computed for 5 test entities — values in \[0,1\], no NaN or inf

* P2-M10 Final Anomaly Score accepts mock DeviationScore(0.4), DriftScore(0.3), SimilarityScore(0.8) → score ≈ 0.44, severity=MEDIUM

## **Week 4 Integration Gates (End-to-End)**

* Full pipeline test: inject 100 synthetic events via P2-M1 → encoding → scoring → alert. At least 1 HIGH alert produced.

* P2-M14 Slack notifier sends a test alert to the team's test Slack channel

* P2-M14 WebSocket /alerts/stream delivers events to a browser client in real-time

* All module unit test suites pass: pytest tests/ → 0 failures

* README.md has: setup instructions, docker-compose commands, how to run training, how to run inference, how to trigger a test alert

* Model registry has at least 1 registered ArtifactBundle that the entire team can load from a shared path

*Team 189 | Behavioral Anomaly Detection Platform | Capstone Project — updated for the Phase 1 Architecture Addendum*