**CAPSTONE PROJECT TEAM PLANNER**

*Behavioral Anomaly Detection Architecture – End to End*

Team 189 · 3 Members · 4-Week Sprint Plan · 20 Modules · 2 Phases · Full Dependency Mapping · Git Workflow

| Revision note This edition incorporates the Phase 1 Architecture Update Addendum. Updated content is marked with an orange UPDATED tag: Section 6 module guides P1-M1–P1-M4 (revised steps and AI Prompt Briefs), Section 7 Risk Register (two new realized risks), and a forward-looking note on P2-M2 (Record Encoding). Sections 1–5, Week 3–4 plans, Phase 2 module guides (P2-M3 onward), and Section 8 are unaffected and unchanged from the original plan. |
| :---- |

| Revision note — Phase 3 No-LLM remodel Sections 9–14 (Phase 3) have been rewritten as a 12-module plan with no LLM API dependency. The LLM Explanation Service (old P3-M8) and the separate Recommendation Engine (old P3-M9) are merged into one deterministic Knowledge Base & Guidance Engine (P3-M8) that serves static textbook knowledge per detected problem type; old P3-M10 to P3-M13 are renumbered P3-M9 to P3-M12. See the Old → New Module Crosswalk in Section 9. Sections 1–8 are unchanged. |
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

* 9\. Phase 3 — Platform Extension Overview & Scope (12 modules, No-LLM remodel)  
* 10\. Phase 3 Module Dependency & Parallelization Map  
* 11\. Phase 3 Team Role Assignments (Tracks A–D)  
* 12\. Phase 3 Sprint Plan (Weeks 5–8)  
* 13\. Phase 3 Module Implementation Guides (P3-M1 → P3-M12) — incl. Do's and Don'ts per module  
* 14\. Phase 3 Risk Register Additions

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

# **9\. Phase 3 — Platform Extension Overview & Scope**

| Revised — Phase 3 Platform Extension (No-LLM Remodel) Sections 1–8 above are UNCHANGED and remain the canonical Phase 1/Phase 2 team planner. Sections 9–14 below replace the earlier 13-module Phase 3 plan with a 12-module plan. Phase 3 still turns the existing single-tenant detection pipeline into a multi-tenant, explainable operations platform: Notifications, Identity/Tenancy, Onboarding, Cloud Connect (wraps the existing live_ingestion/ package), and RCA (Evidence Builder → Hypothesis Engine → Confidence Scorer → Knowledge Base & Guidance Engine). The one architectural change: explanations no longer come from an LLM API call. The LLM Explanation Service (old P3-M8) and the separate Recommendation Engine (old P3-M9) are merged into a single deterministic module, P3-M8 Knowledge Base & Guidance Engine, which serves static textbook knowledge for each type of problem the platform detects. No Phase 3 module calls an LLM or any other external API to produce explanations. Old P3-M10 to P3-M13 are renumbered P3-M9 to P3-M12 (crosswalk below). In scope: notification channels (Email/Slack extended, SMS/Webhook/PagerDuty new), 3-role tenancy, guided onboarding, read-only cloud resource discovery, evidence-first RCA, and textbook-knowledge explanations plus investigative checks. Out of scope: any LLM or generative-AI call, automatic remediation, enterprise SSO/SCIM, billing, full SIEM replacement — the platform's read-only cloud connectors make automatic remediation structurally impossible, not just policy-excluded. |
| :---- |

## **What Changed and Why**

| Area | Earlier plan (13 modules) | Remodeled plan (12 modules) | Why |
| :---- | :---- | :---- | :---- |
| Explanation source | LLM API call over a finished RCACase (PromptBuilder → ExplanationService → response validation) | Static, version-controlled knowledge base (YAML) with textbook definitions per problem type; only whitelisted placeholders are filled from the RCACase | Removes the LLM provider, API keys, cost/rate limits, prompt design, response validation and mock adapter from scope |
| Recommended checks | Attached to each CandidateCause by P3-M7's rules, then reshaped by a separate Recommendation Engine (P3-M9) | Authored once in the knowledge base and looked up by cause category in the same module (P3-M8) | Old M9 was kept separate only so a bad LLM narrative could not invent an action. With no generative step, the split has no purpose |
| Module count | 13 | 12 (old M8 + old M9 merged; old M10–M13 renumbered) | Fewer modules, one fewer fork to coordinate |
| Delivery | On-demand POST with caching keyed on (rca_case hash, explanation_version) | GET, computed on read, stamped with kb_version. No cache, no persistence | The computation is a dictionary lookup plus string templating |
| Failure modes | LLM timeout/error, hallucinated cause, prompt injection via resource tags, provider outage on demo day | Malformed or incomplete knowledge base, caught at startup and in CI. Runtime fallback to the UNKNOWN entry | Failures move from run time (unpredictable) to build time (testable) |
| Demo risk | Must rehearse LLM-available and LLM-unavailable paths | RCA chain has no external dependency. Rehearse confident-category and UNKNOWN paths instead | The RCA chain cannot fail live because of a third-party service |
| CandidateCause shape | Carried recommended_checks | Carries rule_id, supporting_evidence_keys, contradicting_evidence_keys; recommended_checks removed | Keeps M7 = "what type of problem", M8 = "what that means and what to check" |

## **Old → New Module Crosswalk**

*Use this when reading older artifacts (blueprint, slide deck, earlier planner drafts) that still use the 13-module numbering.*

| Old ID | Old name | New ID | Disposition |
| :---- | :---- | :---- | :---- |
| P3-M1 | Notification Foundation | P3-M1 | Unchanged |
| P3-M2 | Platform Schema (Postgres) | P3-M2 | Unchanged |
| P3-M3 | Identity & Tenancy | P3-M3 | Unchanged |
| P3-M4 | Onboarding Flow | P3-M4 | Unchanged (downstream IDs renumbered) |
| P3-M5 | Cloud Connect Layer | P3-M5 | Unchanged (dependency note on P3-M6 clarified) |
| P3-M6 | RCA Evidence Builder | P3-M6 | Minor: commit rca/types.py first; "zero-LLM" wording widened to "no external calls" |
| P3-M7 | Hypothesis Engine + Confidence | P3-M7 | Changed: CandidateCause loses recommended_checks, gains evidence keys and rule_id; adds KB coverage contract test |
| P3-M8 | Explainable AI (LLM Explanation Service) | P3-M8 | Replaced: now Knowledge Base & Guidance Engine (deterministic, no API) |
| P3-M9 | Recommendation Engine v1 | P3-M8 | Merged into the new P3-M8 |
| P3-M10 | SMS / Webhook / PagerDuty Channels | P3-M9 | Renumbered |
| P3-M11 | Dashboard Evolution | P3-M10 | Renumbered; Explanation panel redesigned around structured KB sections |
| P3-M12 | Full Demo Integration | P3-M11 | Renumbered; LLM-unavailable test replaced by UNKNOWN-path and KB-coverage tests |
| P3-M13 | Security Hardening Pass | P3-M12 | Renumbered |

## **Phase 3 Critical Path & Parallel Tracks**

| Two long chains converge at the dashboard (P3-M10) and the demo (P3-M11): Platform chain:   P3-M2 (Platform Schema) → P3-M3 (Identity & Tenancy) → P3-M5 (Cloud Connect)      → P3-M4 (Onboarding) → P3-M10 (Dashboard) → P3-M11 (Full Demo Integration) RCA chain:   P3-M2 (Platform Schema) → P3-M6 (Evidence Builder) → P3-M7 (Hypothesis + Confidence)      → P3-M8 (Knowledge Base & Guidance Engine) → P3-M10 (Dashboard) → P3-M11 (Full Demo Integration) Parallel from day 1:   P3-M1 (Notification Foundation) runs independently of P3-M2/M3 — start immediately.   P3-M8 content authoring (the knowledge_base.yaml text) has no code dependency — the 10 cause categories are already fixed — so it can start on day 1 alongside everything else. Parallel once P3-M6 commits phase3/rca/types.py:   P3-M8 code (KnowledgeLoader, ExplanationBuilder, RecommendationEngine) can be built and tested against fixture RCACase objects before P3-M6/M7 finish. Parallel once P3-M1/M3/M5 land:   P3-M4 (Onboarding) and P3-M12 (Security Hardening) can proceed alongside the RCA chain — neither depends on RCA output. Parallel once P3-M1 lands:   P3-M9 (SMS/Webhook/PagerDuty) can proceed alongside the entire RCA chain (M6–M8). The old P3-M8 ∥ P3-M9 fork no longer exists; its replacement is the content-vs-code split inside P3-M8. P3-M11 (Full Demo Integration) is terminal — the only module that waits on everything else. |
| :---- |

*Dependency note: P3-M6 hard-depends only on P3-M2 (the rca_cases table). P3-M5's cloud_resources rows are an optional enrichment for the RCA timeline, not a blocker. The earlier plan listed P3-M5 as a required predecessor of P3-M6 in one table and not in another; this edition treats it as optional consistently.*

# **10\. Phase 3 Module Dependency & Parallelization Map**

*Same format as Section 2's Module Dependency Map. 'Depends On (P3)' lists only new Phase 3 prerequisites — see each module's guide in Section 13 for its existing Phase 1/2 dependencies. 'Parallel With' lists modules that can be worked simultaneously by a different team member without blocking either side.*

| Module | Name | Owner | Priority | Depends On (P3) | Required By |
| :---- | :---- | :---- | :---- | :---- | :---- |
| P3-M1 | Notification Foundation | Member C (extends P2-M14 ownership) | CRITICAL | — (start immediately) | P3-M4, P3-M9, P3-M11 |
| P3-M2 | Platform Schema (Postgres) | Member B (extends P2-M6/entity-store ownership) | CRITICAL | — (start immediately) | P3-M3, P3-M5, P3-M6, P3-M12 |
| P3-M3 | Identity & Tenancy | Member B | CRITICAL | P3-M2 | P3-M4, P3-M5, P3-M12 |
| P3-M4 | Onboarding Flow | Member C | HIGH | P3-M1, P3-M3, P3-M5 | P3-M10, P3-M11 |
| P3-M5 | Cloud Connect Layer | Member B | HIGH | P3-M2, P3-M3 | P3-M4, P3-M11 (optional enrichment for P3-M6) |
| P3-M6 | RCA Evidence Builder | RCA Track (Member A once Phase 1 closes, or shared) | CRITICAL | P3-M2 (optional: P3-M5) | P3-M7 |
| P3-M7 | Hypothesis Engine + Confidence | RCA Track | CRITICAL | P3-M6 | P3-M8 |
| P3-M8 | Knowledge Base & Guidance Engine | RCA Track | HIGH | P3-M7 for the final category list; code can start against fixtures once P3-M6 commits rca/types.py; content authoring has no dependency | P3-M10, P3-M11 |
| P3-M9 | SMS / Webhook / PagerDuty Channels | Member C | LOW/P1 | P3-M1 | P3-M11 (optional channels) |
| P3-M10 | Dashboard Evolution | Frontend/shared owner | HIGH | P3-M4, P3-M6, P3-M7, P3-M8 | P3-M11 |
| P3-M11 | Full Demo Integration | Whole team | CRITICAL | P3-M1 through P3-M10 | — (terminal) |
| P3-M12 | Security Hardening Pass | Member C / whole team | HIGH | P3-M3, P3-M5 | — (terminal) |

**Parallel-work quick reference (who can work with whom, at the same time, right now):**

| Module | Name | Can run in parallel with |
| :---- | :---- | :---- |
| P3-M1 | Notification Foundation | P3-M2, P3-M3, P3-M8 (content authoring) |
| P3-M2 | Platform Schema (Postgres) | P3-M1, P3-M8 (content authoring) |
| P3-M3 | Identity & Tenancy | P3-M1 |
| P3-M4 | Onboarding Flow | P3-M6, P3-M12 |
| P3-M5 | Cloud Connect Layer | P3-M3 |
| P3-M6 | RCA Evidence Builder | P3-M4, P3-M5, P3-M8 (content authoring), P3-M12 |
| P3-M7 | Hypothesis Engine + Confidence | P3-M8 (content authoring and fixture-based code), P3-M9, P3-M12 |
| P3-M8 | Knowledge Base & Guidance Engine | Content: any module. Code: P3-M7, P3-M9, P3-M12 |
| P3-M9 | SMS / Webhook / PagerDuty Channels | P3-M6, P3-M7, P3-M8 |
| P3-M10 | Dashboard Evolution | Can start onboarding pages as soon as P3-M4's API contract is stable; incident/RCA pages can build against a mocked API (including mock explanation fixtures) before P3-M6–M8 finish |
| P3-M11 | Full Demo Integration | — |
| P3-M12 | Security Hardening Pass | P3-M6, P3-M7, P3-M8, P3-M10 |

# **11\. Phase 3 Team Role Assignments (Tracks A–D)**

*Mapped onto the existing 3-member team (Section 3). Member A's Phase 1 modules (epoch 10/20, TRAIN\_LR reconciliation still open per Section 6/2d) take priority — confirm with the team whether Member A joins a Phase 3 track now or after Phase 1 sign-off. \[OPEN DECISION\]*

| Track | Suggested Owner | Modules | Rationale |
| :---- | :---- | :---- | :---- |
| A — Notifications & Onboarding | Member C (extends P2-M14 ownership) | P3-M1, P3-M4, P3-M9, P3-M12 | Direct extension of existing alerting/notifier ownership |
| B — Platform & Cloud Connect | Member B (extends P2-M6/entity-store ownership) | P3-M2, P3-M3, P3-M5 | Direct extension of existing storage/infra ownership |
| C — RCA & Knowledge | Member A once Phase 1 closes out, or shared | P3-M6, P3-M7, P3-M8 | Now three modules instead of four. P3-M8 is content-heavy rather than integration-heavy, so the knowledge base text can be split across members and cross-reviewed; domain accuracy matters more than coding depth there |
| D — Dashboard | Existing frontend/shared scaffold owner | P3-M10 | Continues the in-progress React scaffold work |

*Merge order: P3-M2 (schema) before anything else touches Postgres — P3-M1 before P3-M9 — P3-M6's phase3/rca/types.py before P3-M7/M8 code — the KB coverage contract test (every category in hypothesis\_rules.yaml has a knowledge-base entry) is the merge gate for both P3-M7 and P3-M8, so they can land in either order as long as it is green on dev. P3-M11 (whole team, integration week) is the only module that requires every track to have already merged to dev.*

# **12\. Phase 3 Sprint Plan (Weeks 5–8)**

*Continues directly from Section 5's Week 4\. Assumes Phase 1/2 milestones are signed off before Week 5 begins.*

## **Week 5: Foundations — Schema, Identity, Notification Base**

* Track B: P3-M2 Platform Schema (postgres + pgvector added to docker-compose.yml, migrations for all 11 tables)  
* Track B: P3-M3 Identity & Tenancy (AuthService, MembershipValidator, isolation test suite)  
* Track A: P3-M1 Notification Foundation (NotificationDispatcher, replace hardcoded email recipient)  
* Track C (if capacity): freeze the knowledge-base YAML schema and the 10-category list in a one-page decision note, so content authoring can start in Week 6 without rework  
* Milestone: two seeded tenants pass the cross-tenant isolation test suite

## **Week 6: Cloud Connect, Onboarding, RCA Evidence, Knowledge Content**

* Track B: P3-M5 Cloud Connect Layer (list\_resources() on all 4 existing connectors, CredentialStore)  
* Track A: P3-M4 Onboarding Flow (orchestration over P3-M1/M3/M5)  
* Track C: P3-M6 Evidence Builder (deterministic RCACase assembly; commit phase3/rca/types.py in the first day or two)  
* Track C (or a second member): P3-M8 content authoring — first draft of knowledge\_base.yaml covering all 10 cause categories, the 3 signal glossary entries, and the 3 confidence-level notes  
* Milestone: a synthetic tenant can complete onboarding end-to-end in the UI; knowledge base draft covers every category

## **Week 7: Hypothesis Engine, Knowledge Engine, Remaining Channels, Security**

* Track C: P3-M7 Hypothesis Engine + Confidence Scorer (hypothesis\_rules.yaml, unit-tested deterministically)  
* Track C: P3-M8 code — KnowledgeLoader, ExplanationBuilder, RecommendationEngine, golden-file tests, KB coverage contract test  
* Track A: P3-M9 SMS/Webhook/PagerDuty channels  
* Track A: P3-M12 Security Hardening Pass (can start once P3-M3/M5 exist — does not wait for RCA)  
* Milestone: a synthetic anomaly produces a persisted RCACase with a non-empty candidate\_causes list, plus a rendered Explanation and Recommended Checks from the knowledge base — all offline, with no API key configured

## **Week 8: Dashboard, Full Demo Integration, Hardening**

* Track D: P3-M10 Dashboard Evolution (onboarding wizard, connections page, Incident/RCA page)  
* Whole team: P3-M11 Full Demo Integration — test both a confident-category path and the UNKNOWN/low-confidence fallback path  
* Track C (or a second member): second-person review pass over knowledge\_base.yaml wording; bump kb\_version  
* Whole team: close out P3-M12 isolation/security test suite  
* Milestone: full workflow demoable end-to-end within the existing 10–15 minute demo script

*Capacity note: removing the LLM integration (provider setup, prompt design, response validation, caching, mock adapter) frees Track C time in Weeks 7–8. Spend it on knowledge-base review and demo rehearsal rather than new features — content quality is now the main determinant of how good the RCA feature looks.*

# **13\. Phase 3 Module Implementation Guides (P3-M1 → P3-M12)**

*Same structure as Section 6's Phase 1/2 guides (Overview / Tech Stack / Depends On / Implementation Steps / Integration / AI Prompt Brief), PLUS two additions the team asked for explicitly: a Do's and Don'ts table, and a Dependency & Parallel Work line. Pair each AI Prompt Brief below with its matching LLM Context Primer in the Directory Structure doc, Section 7e, exactly per the existing Section 6c usage pattern. Note: the 'LLM Context Primers' are prompts for AI-assisted coding during development. They are unrelated to runtime behavior — Phase 3 makes no LLM calls at run time.*

## **P3-M1 — Notification Foundation**

*Status: new for Phase 3\. Owner: Member C (extends P2-M14 ownership). Priority: CRITICAL.*  
**Overview:** Generalize the already-working notification path (existing EmailNotifier used by the demo backend, named SlackNotifier/PagerDutyNotifier) behind a real dispatch \+ policy layer, and remove the hardcoded email recipient discovered in api\_demo\_ext/email\_service.py.  
**Tech Stack:** Python, asyncio, FastAPI, existing BaseNotifier subclasses  
**Depends On (existing system):** P2-M14 (AlertPayload, BaseNotifier \+ existing EmailNotifier/SlackNotifier)

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** — can start immediately  
**Required by:** P3-M4, P3-M9, P3-M11  
**Can run in parallel with:** P3-M2, P3-M3

### **Implementation Steps:**

* Define NotificationEndpoint, NotificationPolicy, NotificationDeliveryResult dataclasses in phase3/shared/types.py  
* Implement NotificationDispatcher.dispatch(payload: AlertPayload, policy) using asyncio.gather(..., return\_exceptions=True) \-- same pattern already specified in P2-M14's own AI Prompt Brief  
* Wrap the existing EmailNotifier: replace the hardcoded recipient with a NotificationEndpoint lookup; keep the existing email\_logs/ fallback behavior as-is  
* Add idempotency key f"{alert\_id}:{endpoint\_id}" so dispatcher retries never double-send  
* Persist every attempt as a NotificationDeliveryResult row (feeds P3-M2 notification\_deliveries table)

### **Integration with the Rest of the System:**

NotificationDispatcher is called from the existing P2-M14 AlertApi right after AlertPayload is assembled \-- it does not replace AlertApi, it is injected as the notifier-fanout step. Feeds delivery status to the Incident dashboard page (P3-M10).

### **AI Prompt Brief for Implementation:**

*Implement a NotificationDispatcher that takes an existing AlertPayload (shared/types.py, frozen \-- do not modify) and a NotificationPolicy, and fans out to the tenant's configured NotificationEndpoints via the existing BaseNotifier subclasses. Use asyncio.gather with return\_exceptions=True so one channel's failure never blocks another. Never let a notification failure raise back into the alerting pipeline. Return a List\[NotificationDeliveryResult\] with success/error/retry\_count per endpoint.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Reuse the existing EmailNotifier/SlackNotifier classes \-- extend, do not rewrite | Do not let a notification failure raise out of AlertApi's request path |
| Keep the existing email\_logs/ dev fallback behavior | Do not hardcode any recipient/channel target anywhere in this module |
| Make every dispatch idempotent on (alert\_id, endpoint\_id) | Do not block on a slow channel (e.g. SMTP timeout) before dispatching to the others |

## **P3-M2 — Platform Schema (Postgres)**

*Status: new for Phase 3\. Owner: Member B (extends P2-M6/entity-store ownership). Priority: CRITICAL.*  
**Overview:** Add the relational platform schema (users, tenants, cloud\_connections, notification\_\*, incidents, rca\_cases, audit\_events) as a NEW Postgres database/service \-- separate from, not a replacement for, the existing PgVectorEntityStore usage in P2-M6.  
**Tech Stack:** PostgreSQL \+ pgvector, Alembic (or equivalent migration tool), SQLAlchemy  
**Depends On (existing system):** None \-- new infrastructure

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** — can start immediately  
**Required by:** P3-M3, P3-M5, P3-M6, P3-M12  
**Can run in parallel with:** P3-M1

### **Implementation Steps:**

* Add a postgres service (pgvector extension enabled) to docker-compose.yml \-- currently missing despite P2-M6 already depending on Postgres  
* Write migrations for: users, tenants, tenant\_memberships, cloud\_connections, cloud\_resources, notification\_endpoints, notification\_policies, notification\_deliveries, incidents, rca\_cases, audit\_events  
* Every table except users gets a tenant\_id column with an index  
* Add PlatformSessionFactory (SQLAlchemy session/engine) in phase3/db/session.py, injected via constructor \-- never imported and instantiated inline (DIP, matches existing project convention)  
* Write a round-trip integration test per table, mirroring the existing tests/integration/phase2/test\_entity\_store\_real\_redis.py real-backend pattern

### **Integration with the Rest of the System:**

This is the storage foundation every other Phase 3 module reads/writes through. It does not touch phase1/, phase2/, or the existing entity-store Postgres usage.

### **AI Prompt Brief for Implementation:**

*Design and implement the Phase 3 platform relational schema using SQLAlchemy \+ a migration tool. Tables: users, tenants, tenant\_memberships, cloud\_connections, cloud\_resources, notification\_endpoints, notification\_policies, notification\_deliveries, incidents, rca\_cases, audit\_events. Every table (except users) carries tenant\_id with an index. Provide PlatformSessionFactory as an injectable session/engine provider \-- no class may call the database connection directly. Add a postgres service with the pgvector extension to docker-compose.yml.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Add tenant\_id \+ index to every table except users | Do not reuse or modify the existing PgVectorEntityStore's tables/schema |
| Use a migration tool (not manual DDL) so schema changes are reviewable in PRs | Do not use Redis as the system of record for anything in this table list |
| Add postgres to docker-compose.yml with the pgvector extension enabled | Do not let any class construct its own DB connection outside PlatformSessionFactory |

## **P3-M3 — Identity & Tenancy**

*Status: new for Phase 3\. Owner: Member B. Priority: CRITICAL.*  
**Overview:** Users, tenants, and 3-role membership (OWNER/OPERATOR/VIEWER). Deliberately not enterprise-grade RBAC or SSO \-- three roles cover every workflow this platform needs.  
**Tech Stack:** FastAPI, Passlib/bcrypt, SQLAlchemy  
**Depends On (existing system):** None

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** P3-M2  
**Required by:** P3-M4, P3-M5, P3-M12  
**Can run in parallel with:** P3-M1

### **Implementation Steps:**

* Implement User/Tenant/TenantMembership/Role dataclasses in phase3/shared/types.py  
* Implement AuthService: register(), login() (bcrypt password hashing), session/JWT issuance  
* Implement MembershipValidator.validate(user\_id, tenant\_id, min\_role) \-\> bool \-- called by every Phase 3 route before touching tenant data  
* Set Tenant.source\_mode ('synthetic' | 'live') as immutable after creation \-- a tenant is never migrated from synthetic to live in place  
* Write the isolation test suite: two tenants, assert every cross-tenant read attempt is rejected before the query even runs

### **Integration with the Rest of the System:**

MembershipValidator is the authorization gate every other Phase 3 route (P3-M4, M5, M11) calls first. Tenant.source\_mode mirrors the source\_mode field already used in live\_ingestion/config/live\_mode.example.yaml.

### **AI Prompt Brief for Implementation:**

*Implement a Phase 3 identity/tenancy layer: User, Tenant, TenantMembership(role: OWNER|OPERATOR|VIEWER) dataclasses; AuthService with bcrypt-hashed passwords and session/JWT issuance; MembershipValidator.validate(user\_id, tenant\_id, min\_role) \-\> bool that every downstream route must call before any tenant-scoped read/write. Tenant.source\_mode is set at creation and never changes. Do not build SSO, SCIM, or more than three roles.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Call MembershipValidator before every tenant-scoped query, not after | Do not build enterprise SSO/SCIM/RBAC beyond the three documented roles |
| Hash passwords with bcrypt/argon2 \-- never store plaintext or reversible encryption | Do not trust a tenant\_id supplied only as a request path/query parameter without a membership check |
| Keep Tenant.source\_mode immutable once set | Do not allow a synthetic tenant to be converted to live in place |

## **P3-M4 — Onboarding Flow**

*Status: new for Phase 3\. Owner: Member C. Priority: HIGH.*  
**Overview:** Registration \-\> tenant creation \-\> cloud connection \-\> credential validation \-\> resource discovery \-\> notification setup \-\> test notification \-\> enable monitoring. Every backend capability this flow calls already exists (P3-M1, M3, M5) \-- this module is orchestration only.  
**Tech Stack:** FastAPI, React (frontend wizard)  
**Depends On (existing system):** live\_ingestion/ health\_check() (existing, reused as-is)

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** P3-M1, P3-M3, P3-M5  
**Required by:** P3-M10, P3-M11  
**Can run in parallel with:** P3-M6, P3-M12

### **Implementation Steps:**

* Implement OnboardingWizardService as a thin state-machine orchestrator over existing services (AuthService, CloudConnectionService, NotificationDispatcher) \-- it must not reimplement any of their logic  
* Step 'Credential Validation' calls the existing Live\*Ingestor.health\_check() directly \-- do not write a new validation path  
* Step 'Test Notification' calls NotificationDispatcher.dispatch() with a synthetic AlertPayload, not a real detection  
* Step 'Enable Monitoring' flips CloudConnection.dry\_run only after an explicit confirm click \-- never silently  
* Persist step completion so a user can resume onboarding after leaving mid-flow

### **Integration with the Rest of the System:**

Sits entirely on top of P3-M1/M3/M5 \-- it is a coordinator, not a new capability. The React wizard (P3-M10) is a thin UI over this service's step API.

### **AI Prompt Brief for Implementation:**

*Implement OnboardingWizardService as a pure orchestrator: Registration \-\> Tenant Creation \-\> Cloud Connection \-\> Credential Validation (call existing health\_check()) \-\> Resource Discovery (call CloudConnectionService.discover\_resources()) \-\> Notification Setup \-\> Test Notification (call NotificationDispatcher) \-\> Enable Monitoring (flip dry\_run only on explicit confirm). Persist per-step completion so onboarding is resumable. Do not reimplement any logic that already exists in P3-M1/M3/M5 or in live\_ingestion/.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Reuse health\_check(), CloudConnectionService, and NotificationDispatcher as-is | Do not reimplement cloud credential validation inside this module |
| Require an explicit confirm step before flipping dry\_run to false | Do not auto-enable live (dry\_run=false) monitoring without an explicit user action |
| Make onboarding resumable from wherever the user left off | Do not block registration on cloud connection \-- a tenant may exist synthetic-only indefinitely |

## **P3-M5 — Cloud Connect Layer**

*Status: new for Phase 3\. Owner: Member B. Priority: HIGH.*  
**Overview:** Thin onboarding-facing wrapper around the existing BaseLiveIngestor connectors, plus the one genuinely new capability they lack: read-only resource inventory discovery.  
**Tech Stack:** Python, boto3/azure-identity/google-cloud-logging/oci (existing deps), cryptography (Fernet)  
**Depends On (existing system):** live\_ingestion/connectors/\*\_live\_ingestor.py (existing, wrapped not replaced); live\_ingestion/iam\_policies/\* (existing, reused verbatim)

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** P3-M2, P3-M3  
**Required by:** P3-M4, P3-M11 (optional resource context for P3-M6)  
**Can run in parallel with:** P3-M3

### **Implementation Steps:**

* Implement CloudConnectionService.validate(cfg) as a direct call to the existing Live\*Ingestor.health\_check() \-- no new validation logic  
* Add list\_resources(resource\_types=None) \-\> List\[ResourceSummary\] as an ADDITIVE abstract method on BaseLiveIngestor; implement it per provider using ONLY verbs already granted by the existing IAM policy files (ec2:DescribeInstances, s3:ListAllMyBuckets, compute.instances.list, storage.buckets.list, etc.)  
* Implement CredentialStore: Fernet-encrypted-at-rest credentials\_cfg persistence, keyed by connection\_id, never logged  
* Implement connection\_repository.py: Postgres CRUD for CloudConnection rows (P3-M2 schema)  
* Add a periodic (e.g. daily) re-health\_check() job that updates last\_validated\_at and flags stale credentials

### **Integration with the Rest of the System:**

Everything below CloudConnectionService is the existing, unmodified live\_ingestion/ package. This module never duplicates poll(), \_map\_to\_raw\_record(), or dry\_run logic.

### **AI Prompt Brief for Implementation:**

*Implement CloudConnectionService as a thin wrapper: validate(cfg) calls the existing Live\*Ingestor.health\_check() unchanged. Add list\_resources(resource\_types=None) as a new abstract method on the existing BaseLiveIngestor (additive only \-- do not change poll() or the constructor contract), implemented per provider using only Describe\*/List\*/Get\* verbs already present in aws\_readonly\_policy.json / azure\_role\_definition.json / gcp\_custom\_role.yaml / oci\_policy.txt. Implement CredentialStore with Fernet encryption at rest, never logging credentials\_cfg. Persist connections via connection\_repository.py against the P3-M2 schema.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Check the existing IAM policy files before adding any new permission for list\_resources() | Do not modify poll(), \_fetch\_raw\_events(), or \_map\_to\_raw\_record() in any existing connector |
| Encrypt credentials\_cfg at rest; never log it (matches the existing connector discipline) | Do not request a new IAM permission for a Phase 3 feature without team sign-off |
| Keep dry\_run default True for every new CloudConnection row, exactly like LiveIngestorConfigData | Do not return raw credentials in any API response, even to an OWNER \-- return a masked reference only |

## **P3-M6 — RCA Evidence Builder**

*Status: new for Phase 3 (minor revision in the No-LLM remodel). Owner: RCA Track (Member A once Phase 1 closes, or shared). Priority: CRITICAL.*  
**Overview:** Deterministically assembles a complete RCACase from the existing Phase 2 outputs already produced for every alert. This is the foundation of the RCA feature, and it is 100% rule-based — no LLM or other external call happens in this module, or anywhere else in the RCA chain.  
**Tech Stack:** Python  
**Depends On (existing system):** AnomalyResult, DeviationResult, DriftResult, EpisodeMatch, CorrelationResult (all existing, frozen, shared/types.py); phase0/ statistical baseline output — OPTIONAL, \[REQUIRES VERIFICATION\] before wiring in

| Change vs. the earlier plan Commit phase3/rca/types.py (RCACase, CandidateCause) within the first day or two of this module. P3-M7 and P3-M8 both build against it, and P3-M8's code work can start on fixture RCACase objects before this module is fully finished. Wording change only otherwise: "zero-LLM" is widened to "no external calls of any kind". |
| :---- |

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** P3-M2 (rca\_cases table). Optional: P3-M5 (cloud\_resources rows can add resource context to the timeline; not a blocker)  
**Required by:** P3-M7  
**Can run in parallel with:** P3-M4, P3-M5, P3-M8 (content authoring), P3-M12

### **Implementation Steps:**

* Define RCACase and CandidateCause dataclasses in phase3/rca/types.py (NOT shared/types.py — see nomenclature/contract note) and commit them first  
* EvidenceBuilder.build(alert\_payload) reads existing AnomalyResult/DeviationResult/DriftResult/EpisodeMatch/CorrelationResult — it must not recompute any score, only assemble what already exists  
* Populate changed\_features, timeline, and observed\_window/baseline\_window purely from existing fields — no new inference logic in this module  
* If phase0/ is confirmed integrated, add its z-score output as a statistical\_evidence field; otherwise leave it absent and documented as deferred  
* Record 'unknowns' explicitly for any evidence that is missing, so downstream modules can say so instead of guessing  
* Persist the RCACase to the rca\_cases table (P3-M2) keyed by incident\_id

### **Integration with the Rest of the System:**

Sits directly downstream of the existing P2-M10/M12 outputs. Feeds P3-M7. Must be callable and testable with no network access of any kind.

### **AI Prompt Brief for Implementation:**

*Implement EvidenceBuilder.build(alert\_payload: AlertPayload) \-\> RCACase, reading only already-computed values from the existing, frozen AnomalyResult/DeviationResult/DriftResult/EpisodeMatch/CorrelationResult dataclasses — do not recompute any score or introduce new statistical logic. Populate RCACase's evidence fields (component\_scores, changed\_features, behavioral\_deviation, drift\_evidence, similar\_episodes, related\_incidents, timeline, unknowns). This module must be 100% deterministic and testable without any network call — given a fixed input, it always produces the same RCACase.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Only assemble data that already exists in Phase 2's output dataclasses | Do not call an LLM or any external API in this module or later in the RCA chain |
| Keep this module fully deterministic and unit-testable with zero external calls | Do not recompute deviation/drift/similarity — read the existing scores, never re-derive them |
| Explicitly record 'unknowns' when evidence is missing rather than guessing | Do not wire in phase0/ output without first confirming its integration status with the team |
| Commit phase3/rca/types.py first so P3-M7 and P3-M8 can build against it | Do not change RCACase field names after P3-M7/M8 have started without a team PR |

## **P3-M7 — Hypothesis Engine \+ Confidence**

*Status: revised in the No-LLM remodel. Owner: RCA Track. Priority: CRITICAL.*  
**Overview:** Rule-based classification of what TYPE of problem the evidence points to, mirroring the existing EscalationEngine's first-match-wins YAML-rule pattern (P2-M13) rather than introducing a second ML model. This module answers "which category, and how confident". What that category means and what to check next lives in P3-M8's knowledge base.  
**Tech Stack:** Python, YAML rules  
**Depends On (existing system):** None

| Change vs. the earlier plan CandidateCause no longer carries recommended\_checks — that text now lives in P3-M8's knowledge base, the single source of truth for textbook content. CandidateCause gains rule\_id, supporting\_evidence\_keys and contradicting\_evidence\_keys so P3-M8 can state exactly which pieces of evidence back each candidate. New CI gate: every category hypothesis\_rules.yaml can emit must have an entry in knowledge\_base.yaml. |
| :---- |

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** P3-M6  
**Required by:** P3-M8  
**Can run in parallel with:** P3-M8 (content authoring, and code built against fixtures), P3-M9, P3-M12

### **Implementation Steps:**

* Define hypothesis\_rules.yaml with candidate cause categories: BEHAVIOR\_CHANGE, DRIFT, RESOURCE\_CHANGE, DEPLOYMENT\_CHANGE, TRAFFIC\_CHANGE, CONFIGURATION\_CHANGE, DEPENDENCY\_ISSUE, REGIONAL\_ISSUE, CLOUD\_PROVIDER\_EVENT, UNKNOWN  
* Give every rule a stable rule\_id and list the RCACase evidence keys it reads, so each CandidateCause can report which evidence supported or contradicted it  
* HypothesisEngine.generate(rca\_case) evaluates rules in order, first-match-wins, exactly like EscalationEngine  
* ConfidenceScorer.score(candidate\_cause, rca\_case): HIGH if \>=2 independent evidence categories agree, MEDIUM if exactly 1 supports with no contradiction, LOW otherwise  
* UNKNOWN is always a valid, honest output when no rule matches confidently — never force a guess  
* Add the KB coverage contract test (tests/unit/phase3/knowledge/test\_kb\_coverage\_contract.py): the set of categories in hypothesis\_rules.yaml must be a subset of the keys under causes: in knowledge\_base.yaml  
* Write unit tests: given fixed evidence, assert the exact candidate\_causes list and confidence produced (fully deterministic, like P2-M13's own test pattern)

### **Integration with the Rest of the System:**

Populates RCACase.candidate\_causes and RCACase.confidence. Consumed by P3-M8 (Knowledge Base & Guidance Engine), which turns the top candidate into a textbook explanation and a list of investigative checks. Nothing in this module or downstream of it calls an external service.

### **AI Prompt Brief for Implementation:**

*Implement HypothesisEngine using a first-match-wins YAML rules file (phase3/rca/hypothesis\_rules.yaml), following the exact same pattern as the existing P2-M13 EscalationEngine. Candidate cause categories: BEHAVIOR\_CHANGE, DRIFT, RESOURCE\_CHANGE, DEPLOYMENT\_CHANGE, TRAFFIC\_CHANGE, CONFIGURATION\_CHANGE, DEPENDENCY\_ISSUE, REGIONAL\_ISSUE, CLOUD\_PROVIDER\_EVENT, UNKNOWN. Each CandidateCause carries cause\_category, confidence, rule\_id, supporting\_evidence\_keys and contradicting\_evidence\_keys — it does NOT carry recommended checks. Implement ConfidenceScorer with a 3-level scale (HIGH/MEDIUM/LOW) based on how many independent evidence categories agree — never output a fabricated decimal confidence value. No LLM or network calls.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Mirror EscalationEngine's first-match-wins YAML pattern exactly | Do not train or introduce a second ML model here — this stays rule-based and auditable |
| Let UNKNOWN be a valid, final output when evidence doesn't support a confident hypothesis | Do not add an LLM or any external call — nothing in Phase 3 generates text with a model |
| Keep confidence to a 3-level ordinal scale, never a manufactured float | Do not present correlation-only evidence as a HIGH-confidence causal hypothesis |
| Keep the category list identical to the knowledge base's causes: keys (enforced by the contract test) | Do not add a new category to hypothesis\_rules.yaml without adding its knowledge-base entry in the same PR |

## **P3-M8 — Knowledge Base & Guidance Engine**

*Status: NEW — replaces the earlier P3-M8 (Explainable AI / LLM Explanation Service) and P3-M9 (Recommendation Engine v1). Owner: RCA Track. Priority: HIGH.*  
**Overview:** Serves textbook-style knowledge for each type of problem the platform detects, deterministically. Given a completed RCACase, (1) ExplanationBuilder assembles a structured Explanation: what this type of problem is, how it was detected (a plain-language glossary of the deviation, drift and novelty signals), the common real-world causes, why it matters, the evidence in this case that points to it, what the confidence level means, and the limits of the analysis; (2) RecommendationEngine returns the investigative checks (Recommended Check → Why → Expected Result → Risk) written for that category. All content is static, version-controlled YAML that humans review. The only dynamic part is a small set of whitelisted values (entity, cloud, region, scores) substituted from the RCACase. No LLM, no network call, no API key, no per-request cost.  
**Tech Stack:** Python, YAML, string.Template  
**Depends On (existing system):** None

| Why one module instead of two The earlier plan kept the Recommendation Engine separate from the LLM explainer so that a bad generated narrative could never invent a bad action. With no generative step, that separation has no purpose, and both outputs are lookups over the same content keyed by the same cause category. Merging them removes a module, a fork to coordinate, and a second copy of the check text to keep consistent. |
| :---- |

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** P3-M7 for the final category list and CandidateCause shape. The module has two halves with different dependencies: content authoring (knowledge\_base.yaml) has none and can start on day 1; code can be built and tested against fixture RCACase objects as soon as P3-M6 commits phase3/rca/types.py  
**Required by:** P3-M10, P3-M11  
**Can run in parallel with:** P3-M9, P3-M12, and (for content authoring) every other module

### **Knowledge Base Structure (phase3/knowledge/knowledge\_base.yaml):**

| Top-level key | Keyed by | Purpose |
| :---- | :---- | :---- |
| kb\_version | — | Semantic version string. Stamped on every Explanation and RecommendedCheck list. Bump on any wording change |
| causes | cause\_category (the 10 values from P3-M7, including UNKNOWN) | title, definition, how\_it\_shows\_up, common\_causes, why\_it\_matters, recommended\_checks, limitations, further\_reading |
| signals | deviation, drift, novelty | Plain-language description of what each score component measures and how to read a high value. Lets every explanation say how the anomaly was detected |
| confidence\_levels | HIGH, MEDIUM, LOW | Fixed text explaining what each level means (agreement between independent evidence categories). No numeric probability |

Example entry (illustrative wording — the team reviews and owns final text):

```yaml
kb_version: "1.0.0"

causes:
  DRIFT:
    title: "Gradual behavioral drift"
    definition: >
      Drift means the overall pattern of an entity's behavior has slowly moved away
      from its longer-term baseline, rather than one reading being unusual.
    how_it_shows_up: >
      The recent behavior distribution differs measurably from the baseline window even
      though no single reading looks extreme. Here the drift score was ${drift_score}.
    common_causes:
      - Organic workload growth or a seasonal / business-cycle shift
      - A slow resource leak or gradual capacity exhaustion
      - A gradual change in client or traffic mix
    why_it_matters: >
      Drift is easy to miss because no single point crosses a threshold. Left alone it can
      turn into saturation, or into a baseline that no longer reflects healthy behavior.
    recommended_checks:
      - check: "Compare the last 30 days of the affected metrics against the prior 90 days"
        why: "Separates a steady ramp from a one-time step change"
        expected_result: "A smooth ramp suggests growth or a leak; a step suggests a change event"
        risk: "none - read-only lookup"
    limitations: >
      Drift shows that behavior changed, not why. It can be entirely healthy, such as planned growth.
    further_reading: []   # only add sources the team has actually verified
```

Whitelisted placeholders (anything else fails validation at load time): entity\_id, cloud\_provider, region, final\_score, severity, deviation\_score, drift\_score, similarity\_score, group\_size, top\_changed\_feature.

### **Implementation Steps:**

* Define KnowledgeEntry, SignalEntry, Explanation, ExplanationSection and RecommendedCheck dataclasses in phase3/knowledge/types.py. Explanation carries rca\_case\_id, cause\_category, headline, sections, kb\_version and is\_fallback (True when the UNKNOWN entry was used because no confident category exists)  
* Author knowledge\_base.yaml: 10 cause entries, 3 signal entries, 3 confidence-level notes. Every entry is written as general textbook knowledge ("commonly caused by…"), hedged, with a limitations field. A second team member reviews every entry. Cite only sources the team has verified  
* Implement KnowledgeLoader.load(path): parse the YAML once at startup, validate the schema (required fields non-empty, every recommended check has check/why/expected\_result/risk, every placeholder is on the whitelist), cache in memory, and fail fast with a clear error. The path or parsed dict is injected through the constructor (DIP — no class reads config inline)  
* Implement ExplanationBuilder.build(rca\_case) \-\> Explanation: take the top-ranked candidate cause, look up its entry (fall back to UNKNOWN), select the signal glossary entries for the score components that contributed, render the "evidence for this case" lines from RCACase fields and the CandidateCause's supporting\_evidence\_keys, fill placeholders with string.Template.safe\_substitute over the whitelist, add the confidence-level note, and stamp kb\_version  
* Implement RecommendationEngine.recommend(rca\_case) \-\> List\[RecommendedCheck\]: same lookup, deterministic order, de-duplicated across multiple candidate causes while preserving rank. Every field populated for every check ('none — read-only lookup' is a valid and expected risk value given read-only connectors)  
* Expose GET /incidents/{incident\_id}/explanation and GET /incidents/{incident\_id}/recommendations in the existing rca router, both behind MembershipValidator (P3-M3). Computed on read. Nothing cached, nothing persisted, no new table  
* Tests: (a) KB coverage contract — every category in hypothesis\_rules.yaml has a knowledge-base entry; (b) schema and placeholder validation, including a deliberately broken YAML that must fail at load; (c) golden-file tests — fixed RCACase in, exact Explanation and check list out; (d) fallback test — unknown category or empty candidate\_causes yields the UNKNOWN entry with is\_fallback=True; (e) a no-network run of the whole module's test suite with sockets disabled, proving there are no hidden external calls  
* Optional stretch (drop first if time-boxed): a small keyword-to-family map over metric\_name (for example network egress, CPU, storage availability) that appends one line of textbook context per affected metric family. Keep it keyword-based, not exhaustive — the metric\_name vocabulary is data-dependent (127 classes in the current corpus sample) and must not be hardcoded

### **Integration with the Rest of the System:**

Reads a completed RCACase (P3-M6/M7) and returns structured JSON that the Incident/RCA page (P3-M10) renders section by section. Never writes to the database and never sits on the alert-generation path — alert creation does not wait on it and it cannot fail an alert. The knowledge base file is a repo artifact, versioned in Git and reviewed in PRs like any other code.

### **AI Prompt Brief for Implementation:**

*Implement three classes in phase3/knowledge/: KnowledgeLoader, ExplanationBuilder and RecommendationEngine, plus dataclasses KnowledgeEntry, SignalEntry, Explanation, ExplanationSection and RecommendedCheck in phase3/knowledge/types.py. KnowledgeLoader parses and validates phase3/knowledge/knowledge\_base.yaml at startup (required fields, complete recommended checks, placeholders limited to a fixed whitelist) and fails fast on any error. ExplanationBuilder.build(rca\_case: RCACase) \-\> Explanation looks up the top candidate's cause\_category (falling back to the UNKNOWN entry with is\_fallback=True), fills whitelisted placeholders from the RCACase using string.Template.safe\_substitute — never str.format or f-strings on knowledge-base text — and stamps kb\_version. RecommendationEngine.recommend(rca\_case) \-\> List\[RecommendedCheck\] returns only read-only investigative checks from the same entry, each with check, why, expected\_result and risk populated. Do not call any LLM, HTTP endpoint or other network service anywhere in this module, and do not add any dependency that would require an API key. Only import from phase3/rca/types.py, phase3/knowledge/types.py and the standard library plus PyYAML.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Write entries as hedged textbook knowledge ("commonly caused by…") and always fill the limitations field | Do not state a specific root cause as established fact — the knowledge base explains categories, not the certainty of this incident |
| Keep every case-specific statement traceable to a named RCACase field | Do not let the explanation change severity, score, or whether an anomaly occurred — those are already fixed in the RCACase |
| Treat UNKNOWN as a complete, honest entry with its own explanation and checks | Do not render a blank panel or raise an error when no category matches — return the UNKNOWN entry |
| Validate the whole file at startup and in CI so problems surface at build time | Do not discover a malformed entry on demo day — never lazy-validate at request time |
| Bump kb\_version on any wording change and review content changes like code | Do not allow tenant- or user-editable knowledge-base content in v1 |
| Use string.Template.safe\_substitute with a fixed whitelist | Do not use str.format, f-strings or eval on knowledge-base text mixed with case values |
| Provide curated, read-only threat-specific mitigation as advisory guidance for human operators (approved WP-C/WP-F scope); make clear it is not a diagnosis or an executable plan | Do not execute cloud changes, perform write/delete actions, imply that the platform will remediate, or let mitigation text alter severity or score |
| Keep the module offline (no HTTP client, no SDK, no secrets) | Do not add a network or LLM dependency later "just for nicer wording" — that reopens the risk this remodel removed |

## **P3-M9 — SMS / Webhook / PagerDuty Channels**

*Status: new for Phase 3 (renumbered from P3-M10)\. Owner: Member C. Priority: LOW/P1.*  
**Overview:** Completes the notification channel matrix. SMS is escalation-only \-- CRITICAL severity plus off-hours or explicit opt-in, never a default/primary channel.  
**Tech Stack:** Twilio or equivalent SMS API, HMAC signing, PagerDuty Events API v2  
**Depends On (existing system):** BaseNotifier (existing); PagerDutyNotifier (existing name \-- verify implementation status)

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** P3-M1  
**Required by:** P3-M11 (optional channels)  
**Can run in parallel with:** P3-M6, P3-M7, P3-M8

### **Implementation Steps:**

* SmsNotifier(BaseNotifier): trigger only for severity=CRITICAL AND (off business-hours OR explicit tenant opt-in); message body is metadata-only, never raw telemetry  
* WebhookNotifier(BaseNotifier): generic outbound POST of AlertPayload JSON, HMAC-signed with a per-endpoint shared secret in an X-Capstone-Signature header  
* Verify PagerDutyNotifier's current implementation status against the existing AI Prompt Brief in P2-M14; complete against Events API v2 if stubbed  
* Confirm current free-tier/trial terms for the chosen SMS provider before relying on it for a demo

### **Integration with the Rest of the System:**

All three register with the existing BaseNotifier list already injected into NotificationDispatcher (P3-M1) \-- no changes needed to the dispatcher itself.

### **AI Prompt Brief for Implementation:**

*Implement SmsNotifier(BaseNotifier) restricted to CRITICAL severity plus an off-hours or explicit-opt-in gate, sending metadata-only messages (entity\_id, cloud\_provider, region, 'check dashboard' \-- never raw telemetry). Implement WebhookNotifier(BaseNotifier) posting AlertPayload JSON with an HMAC-SHA256 signature in X-Capstone-Signature, using a per-endpoint shared secret. Verify and, if incomplete, finish PagerDutyNotifier against PagerDuty Events API v2 per the existing P2-M14 AI Prompt Brief.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Gate SMS to CRITICAL \+ off-hours/opt-in only \-- never a default channel | Do not use SMS as a primary/default notification channel for any severity |
| Sign every webhook payload with HMAC and a per-endpoint secret | Do not send raw telemetry or score breakdowns via SMS |
| Keep SMS message bodies metadata-only | Do not ship an unsigned webhook payload |

## **P3-M10 — Dashboard Evolution**

*Status: new for Phase 3 (renumbered from P3-M11; Explanation panel redesigned in the No-LLM remodel). Owner: Frontend/shared owner. Priority: HIGH.*  
**Overview:** Evolves the existing scaffold from 'alert viewer' to 'investigation console': onboarding wizard, connections/notification management, and the Incident/RCA page (evidence, timeline, candidate causes, knowledge-base explanation, recommended checks).  
**Tech Stack:** React 18, TypeScript, Vite, Tailwind v4, Zustand, React Query, Recharts  
**Depends On (existing system):** Existing 14-page dashboard scaffold, Zustand stores, React Query, Recharts

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** P3-M4, P3-M6, P3-M7, P3-M8  
**Required by:** P3-M11  
**Can run in parallel with:** can start onboarding pages as soon as P3-M4's API contract is stable; incident/RCA pages can build against a mocked API (including mock Explanation fixtures) before P3-M6–M8 finish

### **Implementation Steps:**

* Finish the previously-flagged App.tsx router wiring first — this blocks every new route below  
* Add onboarding wizard pages matching P3-M4's step API 1:1  
* Add Connections \+ Notification Endpoints management pages under Settings  
* Add the Incident/RCA page: Evidence tab, Timeline tab, Candidate Causes list (with confidence badges), Explanation panel, Recommended Checks checklist  
* Add the incident lifecycle panel: OPEN/ACKNOWLEDGED/RESOLVED state, operator acknowledge/resolve/reopen controls, resolution type/note capture, and the recovery suggestion indicator
* Drive active, critical, resolved-today and mean-time-to-resolve dashboard KPIs from tenant-scoped lifecycle records; resolved incidents must not remain in the active alert feed

### **Incident Lifecycle Baseline Policy**

| Resolution | Baseline action | Default policy |
| :--- | :--- | :--- |
| FIXED | Keep the pre-incident centroid/history; discard quarantined incident embeddings; unfreeze | Do not adapt from the anomalous interval |
| AUTO_RECOVERED | Same as FIXED | Automatic resolution remains disabled by default |
| FALSE_POSITIVE | Replay recent quarantined embeddings, then temporarily increase EMA alpha | `adaptation_alpha: 0.35`, `adaptation_window: 20`, `adaptation_batches: 5` |
| EXPECTED_CHANGE | Same bounded adaptation as FALSE_POSITIVE | Settings are configurable under `incident_lifecycle.baseline` |
| Recovery suggestion | Mark recovering after consecutive scores remain below LOW | Threshold `0.2`, 6 batches; tenant auto-resolve defaults off |
| Regression | Link a fresh incident to a recent FIXED incident on the same entity | 30-minute window; do not apply repeat-escalation downgrade |

Per-tenant automatic resolution is opt-in through `tenants.onboarding_state.settings.auto_resolve_incidents`; the platform setting remains false unless explicitly enabled.
* Build the Explanation panel from the structured sections returned by P3-M8 (Summary, What this means, How it was detected, Common causes, Why it matters, Evidence for this case, Limitations), with the kb\_version shown as a small footer for auditability  
* Design the fallback state explicitly: when is\_fallback is true, show an "No confident category — here is the evidence we do have" state built from the UNKNOWN entry, never a blank panel  
* Keep MOCK\_MODE working for every new page, with mock fixtures that cover at least one HIGH-confidence category and the UNKNOWN fallback

### **Integration with the Rest of the System:**

Consumes the API surface exposed by P3-M4 (onboarding), P3-M5 (connections), P3-M1 (notification endpoints/policies), and P3-M6–M8 (incident/RCA/explanation/recommendations). The explanation and recommendations endpoints are plain GETs that return immediately, so no polling or long-running loading state is needed.

### **AI Prompt Brief for Implementation:**

*Extend the existing React dashboard: finish App.tsx router wiring, then add an onboarding wizard (mirroring OnboardingWizardService's step sequence), a Connections/Notifications settings area, and a new Incident/RCA page with Evidence, Timeline, Candidate Causes (confidence-badged), Explanation (render the structured sections from GET /incidents/{id}/explanation, show kb\_version as a footer, and give the is\_fallback case its own explicit, non-broken state), and Recommended Checks (GET /incidents/{id}/recommendations). Render every knowledge-base and case-derived string as plain text through React's default escaping — never dangerouslySetInnerHTML. Keep the existing MOCK\_MODE flag working end-to-end for every new page so frontend and backend tracks are not blocked on each other.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Finish the existing App.tsx router-wiring gap before adding new routes | Do not let an UNKNOWN or fallback explanation render as a blank or broken page |
| Design the Explanation panel's fallback state explicitly, not as an afterthought | Do not duplicate the existing 14-page scaffold's KPI/Pipeline widgets — extend them |
| Keep every new page working under the existing MOCK\_MODE flag | Do not couple new pages directly to raw backend DB shapes — go through the API layer only |
| Render resource names, tags and knowledge-base text as plain text | Do not use dangerouslySetInnerHTML for any explanation or evidence field |
| Keep lifecycle mutations OPERATOR/OWNER-only and auditable | Do not count RESOLVED incidents as active or let a VIEWER mutate lifecycle state |
| Freeze baseline updates while an incident is active and preserve pre-incident history for FIXED/AUTO_RECOVERED | Do not fold anomalous embeddings into the normal baseline before an operator resolves the incident |

## **P3-M11 — Full Demo Integration**

*Status: new for Phase 3 (renumbered from P3-M12; LLM test paths replaced in the No-LLM remodel). Owner: Whole team. Priority: CRITICAL.*  
**Overview:** End-to-end: onboarding → synthetic (or dry-run live) monitoring → injected anomaly → detection (Phase 2, unmodified) → RCA → knowledge-base explanation and recommended checks → notification → dashboard. This is the single milestone the supervisor demo is built around. Because the RCA chain has no external dependency, the only live-demo failure points left are the notification channels and any live cloud credentials.  
**Tech Stack:** pytest, docker-compose, existing `demo_generator/`
**Depends On (existing system):** Existing 8-scenario synthetic attack generator (demo_generator/)

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** P3-M1 through P3-M10  
**Required by:** — terminal module  
**Can run in parallel with:** — no concurrent-safe module identified

### **Implementation Steps:**

* Run the existing synthetic attack-scenario generator end-to-end against a freshly onboarded demo tenant  
* Confirm the resulting AlertPayload triggers both NotificationDispatcher delivery AND a persisted RCACase  
* Confirm the Incident/RCA dashboard page renders a knowledge-base Explanation and Recommended Checks for a confident-category scenario, and the UNKNOWN fallback state for a scenario with no confident match  
* Confirm the KB coverage contract test and the no-network knowledge-module test run green in CI on the branch used for the demo  
* Time the full flow and cut it to fit the existing 10-15 minute demo script  
* Document a fallback plan for the external services that remain (notification providers, live cloud credentials) — the RCA chain itself needs none (§30 of the Phase 3 blueprint)

### **Integration with the Rest of the System:**

Terminal milestone — exercises every other Phase 3 module together.

### **AI Prompt Brief for Implementation:**

*Write an end-to-end test/demo script that onboards a fresh demo tenant, runs the existing synthetic attack-scenario generator, and asserts: an AlertPayload is produced (Phase 2, unmodified), a NotificationDeliveryResult exists for at least one channel, a persisted RCACase exists with at least one CandidateCause, GET /incidents/{id}/explanation returns a structured Explanation stamped with a kb\_version, GET /incidents/{id}/recommendations returns at least one fully populated RecommendedCheck, and the dashboard's Incident page renders successfully for both a confident-category scenario and a scenario that falls back to UNKNOWN. Time the full run against the existing 10-15 minute demo script.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Test the UNKNOWN fallback path explicitly, not just the confident-category happy path | Do not treat a working happy-path demo as sufficient without also verifying the fallback |
| Reuse the existing synthetic attack-scenario generator rather than writing a new one | Do not demo SMS/PagerDuty as the guaranteed path — Email+Slack must be the fallback-proof path |
| Time-box the run against the existing demo script length | Do not skip tenant-isolation verification just because this is 'just a demo' |
| Do a second-person read-through of the knowledge-base wording before the demo | Do not present the explanation as a diagnosis — it is textbook context plus this case's evidence |

## **P3-M12 — Security Hardening Pass**

*Status: new for Phase 3 (renumbered from P3-M13)\. Owner: Member C / whole team. Priority: HIGH.*  
**Overview:** Structural, testable tenant isolation plus audit logging \-- can be built and tested as soon as tenancy (P3-M3) and at least one tenant-scoped resource (P3-M5) exist, in parallel with the RCA track.  
**Tech Stack:** Python, FastAPI middleware  
**Depends On (existing system):** Existing structured logger factory (shared/logger.py) pattern

### **Dependency & Parallel Work:**

**Depends on (Phase 3):** P3-M3, P3-M5  
**Required by:** — terminal module  
**Can run in parallel with:** P3-M6, P3-M7, P3-M8, P3-M10

### **Implementation Steps:**

* Implement TenantIsolationMiddleware: resolves tenant\_id from the authenticated session, rejects any route that doesn't pass MembershipValidator before the handler runs  
* Implement AuditLogger.record(actor\_user\_id, tenant\_id, action, target) writing to audit\_events (P3-M2), following the existing get\_logger(module\_name) structured-logger pattern  
* Write tests/integration/phase3/test\_tenant\_isolation.py: two tenants, seed one, assert every cross-tenant read returns 403/empty \-- not just that the happy-path filter works  
* Sanitize logs so credential-shaped strings are stripped even from error paths

### **Integration with the Rest of the System:**

Wraps every Phase 3 FastAPI route; reads from P3-M3's MembershipValidator.

### **AI Prompt Brief for Implementation:**

*Implement TenantIsolationMiddleware for FastAPI that resolves tenant\_id from the authenticated session (never trusts a path/query parameter alone) and calls MembershipValidator before any route handler executes. Implement AuditLogger.record(...) writing to the audit\_events table, following the same get\_logger(module\_name) pattern already used elsewhere in the project. Write a dedicated isolation test suite that seeds two tenants and asserts every cross-tenant access attempt is rejected before the query runs, not merely that the correct-tenant query filters correctly.*

### **Do's and Don'ts:**

| Do | Don't |
| :---- | :---- |
| Resolve tenant\_id from the session, never from a client-supplied parameter alone | Do not authorize based on a client-supplied tenant\_id without a membership check |
| Test isolation with two real seeded tenants, not just a single-tenant happy path | Do not skip audit logging for OWNER-level actions |
| Sanitize error logs so no credential-shaped string is ever written | Do not log credentials\_cfg or any masked-credential reference in full |

# **14\. Phase 3 Risk Register Additions**

*Appended to, not replacing, Section 7's existing risk register — the original 8 risks are still valid and unaffected. The LLM-specific risks from the earlier Phase 3 draft (hallucinated causes, provider outage or key/limit problems on demo day, prompt injection via cloud resource tags, LLM-unavailable demo path) no longer apply and have been removed; they are replaced by the knowledge-base risks below.*

| Risk | Likelihood | Description | Mitigation | Owner |
| :---- | :---- | :---- | :---- | :---- |
| Real cloud credentials leaked via logs | Low | New CloudConnectionService/CredentialStore code could accidentally log credentials\_cfg. | Never log credentials\_cfg; Fernet-encrypted at rest; keep the existing live\_ingestion/ discipline. | Track B |
| Knowledge-base content is inaccurate or over-specific | Medium | A textbook entry that states a cause too definitively, or is simply wrong, misleads the user and erodes trust in the RCA feature. | Hedged wording ("commonly caused by"), mandatory limitations field, second-person review of every entry, semantic kb\_version with changes reviewed in PRs, only verified sources in further\_reading. | Track C |
| Knowledge-base coverage gap | Low | A hypothesis rule emits a cause category that has no knowledge-base entry, so the explanation is empty or errors. | CI contract test (every category in hypothesis\_rules.yaml has an entry), startup validation that fails fast, runtime fallback to the UNKNOWN entry. | Track C |
| Explanations feel generic compared with an AI narrative | Medium | Static content may look less impressive to reviewers than generated prose. | Every explanation includes case-specific evidence lines and the signal glossary, so it is visibly tied to this incident. Position determinism as a feature: auditable, offline, reproducible. Optional metric-family notes as a stretch. | Track C / D |
| Template or rendering defect in explanation text | Low | A missing placeholder value, or unescaped resource names/tags rendered in the UI (cross-site scripting). | string.Template.safe\_substitute with a fixed whitelist and a validation test; React default escaping; no dangerouslySetInnerHTML anywhere in the Incident page. | Track C / D |
| Tenant data leaks across boundary | Low if tested, High impact if not | A missed authorization check on any new route/table/Redis key (this now includes the explanation and recommendations endpoints). | MembershipValidator \+ TenantIsolationMiddleware on every route; dedicated 2-tenant isolation test suite. | Track B / A |
| phase0/ integration status unclear | Medium | Wiring unverified phase0/ statistical evidence into RCA could waste effort or ship an unsupported claim. | Confirm with the team before P3-M6 starts; ship without it if unconfirmed. | Track C |
| SMS/PagerDuty free-tier limits block demo | Medium | A provider trial restriction fails silently on demo day. | Treat as P1 channels, not P0; Email+Slack alone must be able to carry the full demo story. | Track A |
| TRAIN\_LR reconciliation (existing risk) delays a stable checkpoint for RCA similarity evidence | Medium | Per Section 6/2d, TRAIN\_LR is still unreconciled (1e-4 vs 3e-4). | Resolve before P3-M6 relies on EpisodeMatch quality. | Member A |

*Team 189 | Behavioral Anomaly Detection Platform | Capstone Project — updated for the Phase 1 Architecture Addendum and the Phase 3 Platform Extension (12-module, No-LLM remodel)*
