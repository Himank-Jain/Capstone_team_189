**CAPSTONE-189**  
**Behavioral Anomaly Detection Platform**

*Uploaded Code Walkthrough — File-by-File Reference*

Covers: generate\_corpus.py · vm\_augmentation.py · generate\_aug\_pairs.py · validate.py

streaming\_aug\_pairs\_dataset.py · tstcc\_encoder.py · ntxent\_loss.py · train\_tstcc.py

tstcc\_encoder\_epoch\_0020.pt · tstcc\_encoder\_final.pt

Mapped against Project Directory Structure (Phase 1 Architecture Addendum) & Team Planner

# **How to Read This Document**

This document walks through every file you uploaded, explains what each one does mechanically (inputs, outputs, internal logic), maps it to the exact Phase/Module ID from the Project Directory Structure and Team Planner, and flags where a file's actual behavior has drifted from what those planning docs currently say. It is meant to be your single reference for 'what is actually happening inside the code right now', independent of what any planning doc claims.

Each file section follows the same structure:

* Module Mapping — which Phase/Module ID (e.g. P1-M2) this file implements, and its role in the pipeline.

* Purpose — the one-paragraph 'why does this file exist'.

* Inputs / Outputs — exactly what goes in and what comes out, with shapes/schemas where relevant.

* How It Works — a numbered walkthrough of the actual logic, in execution order.

* Key Code Sections — the specific functions/classes worth understanding first if you only have five minutes.

* Why It's Necessary — what would break, or what risk it mitigates, if this file didn't exist.

* Watch-Outs / Notes — bugs, dead code, or mismatches with the planning docs found while reading it.

A dedicated section near the end, "Open Items & Discrepancies Found", collects every mismatch across files in one place so you can triage them with your team.

# **1\. File-to-Module Mapping**

The table below is the master index. Files are ordered by where they sit in the data pipeline, not alphabetically — this mirrors the order data actually flows through your system.

| \# | File | Phase / Module | Role | Status |
| :---- | :---- | :---- | :---- | :---- |
| 1 | generate\_corpus.py | Data Simulation(feeds P1-M1) | MongoDB → minute-wise telemetry corpus (pretrain\_corpus.parquet) | Complete |
| 2 | vm\_augmentation.py | P1-M2 — original plan(SUPERSEDED) | Legacy map-style VM-schema augmentation Dataset | Superseded / legacy reference |
| 3 | generate\_aug\_pairs.py | P1-M2 — pair-file writer(SUPERSEDED path) | Streams corpus → writes static aug\_pairs.parquet (view a/b) | Schema mismatch — see Open Items |
| 4 | validate.py | P1-M2 — QA utility | Sanity-checks aug\_pairs.parquet structure | Utility script |
| 5 | streaming\_aug\_pairs\_dataset.py | P1-M2 — CURRENT(StreamingAugPairsDataset) | Streams aug\_pairs.parquet row-group by row-group into training windows | Complete, current design |
| 6 | tstcc\_encoder.py | P1-M3(TstccEncoder) | The contrastive GRU encoder neural network | Complete, training in progress |
| 7 | ntxent\_loss.py | P1-M4(NTXentLossComputer) | NT-Xent / InfoNCE contrastive loss function | Complete |
| 8 | train\_tstcc.py | P1-M4(train\_tstcc.py main()) | Orchestrates the full training run end-to-end | Running — epoch 10→20 |
| 9 | tstcc\_encoder\_epoch\_0020.pt | P1-M4 — artifact | Checkpoint snapshot at epoch 20 (weights \+ optimizer state) | Training artifact |
| 10 | tstcc\_encoder\_final.pt | P1-M4 — artifact | Final encoder weights only, post-training | Training artifact |

# **2\. End-to-End Pipeline Flow**

Read top to bottom — this is literally the order the scripts run in, and each arrow is a file boundary (usually a Parquet file) that the next script reads back in.

1. generate\_corpus.py queries MongoDB (or falls back to a synthetic generator), interpolates daily/hourly seed metrics into minute-level readings, injects synthetic anomalies around real alert timestamps, and writes pretrain\_corpus.parquet — one row per (entity, metric, minute) reading event.

2. generate\_aug\_pairs.py (or, in the current architecture, an event-based equivalent of it) streams that corpus, applies two independent stochastic augmentations (Temporal Jitter \+ Attribute Masking, from vm\_augmentation.py's logic) to every row, and writes aug\_pairs.parquet — every source row becomes a matched view='a'/view='b' pair sharing a pair\_id.

3. validate.py is run ad hoc against aug\_pairs.parquet to confirm pairing integrity, jitter magnitude, and mask-flag correctness before anyone spends GPU time training against it.

4. streaming\_aug\_pairs\_dataset.py wraps aug\_pairs.parquet as a PyTorch IterableDataset. It computes global vocabularies and per-metric z-score statistics once, then streams the file row-group by row-group, building sliding windows of seq\_len consecutive (view\_a, view\_b) reading events per entity.

5. tstcc\_encoder.py defines the TstccEncoder neural network that consumes those windows (numeric \+ categorical \+ timestamp tensors) and produces a 128-dimensional, L2-normalised embedding per window.

6. ntxent\_loss.py's NTXentLossComputer takes the two embeddings produced from view\_a and view\_b of the same window and computes a contrastive loss that pulls matched pairs together and pushes all other pairs in the batch apart.

7. train\_tstcc.py is the conductor: it builds the vocab/stats, constructs the encoder, wires up the loss \+ AdamW optimizer \+ cosine LR schedule, and runs the epoch loop, periodically calling encoder.save\_checkpoint() to write files like tstcc\_encoder\_epoch\_0020.pt, and finally encoder.save\_weights() to write tstcc\_encoder\_final.pt.

**Where this sits in the bigger picture**

Everything above is entirely inside Phase 1 (offline pretraining). None of these files touch Phase 2 (online inference/alerting) — they exist to produce exactly one deliverable for Phase 2 to consume later: a trained TstccEncoder checkpoint that P2-M3 (InferenceEncoder) and P2-M4 (ReferenceEncoderService) will both load.

# **3\. generate\_corpus.py**

| Module Mapping | Pre-Phase-1 data engineering step. Produces the raw input that P1-M1 (CorpusIterator) was designed to consume — this is the 'Data Simulation' workstream referenced in your project history, in its MongoDB-backed (not the Colab IPYNB) form. |
| :---- | :---- |
| **Role in Pipeline** | Turns real cloud-monitoring MongoDB collections (or, if Mongo isn't reachable, a synthetic generator) into a single minute-wise Parquet corpus of telemetry readings, with realistic anomaly labels baked in for later evaluation. |
| **Status** | **Complete — includes both a live-Mongo path and a synthetic fallback path** |

## **Purpose**

This script is the very first stage of the whole pipeline: it manufactures the historical telemetry corpus that everything downstream (augmentation, encoder training) is built from. It pulls real seed data from two MongoDB collections — one holding daily/hourly metric snapshots, one holding activity/alert logs — and expands that sparse seed data into a dense, minute-by-minute time series per entity, complete with injected anomaly windows so the corpus isn't purely 'normal' data. If MongoDB isn't reachable at all, it silently switches to a purely synthetic generator so the rest of the pipeline can still be exercised without a live database.

## **Inputs**

* MongoDB collection cloud\_account\_data\_collection\_daily\_updated — one document per (resource, day, metric), each containing an hourly value array (metric\_value).

* MongoDB collection cloud\_account\_activity\_log\_updated — monitoring alert/event log documents, used only as 'anomaly anchors' (timestamps around which an anomaly should be injected), not as labels that get trained on.

* The CONFIG dict at the top of the file — date range (defaults to November 2025, chosen because EDA found this month has real volume), max\_resources cap, $sample oversampling multiplier, anomaly injection parameters (spike/drop multipliers, duration range), and output paths.

## **Outputs**

* ./corpus\_output/pretrain\_corpus.parquet — the main deliverable. One row per (entity\_id, metric\_name, minute) reading, columns: entity\_id, entity\_type, cloud, namespace, metric\_name, timestamp, value, hour\_anchor, is\_anomaly, anomaly\_type, day\_of\_week, hour\_of\_day, minute\_of\_hour, account\_id, unit.

* ./corpus\_output/corpus\_summary.json — a human-readable run summary: row counts, unique entity/metric counts, cloud distribution, anomaly fraction, date range, and file size — useful for a quick sanity check without opening the Parquet file.

## **How It Works — Step by Step**

8. detect\_cloud(doc) (STEP 1 helper) — infers AWS / Azure / GCP / OCI / Unknown from whichever identifying field is present in a raw Mongo document (resourceId prefix, namespace prefix, uri substring, category substring), because the EDA found that namespace alone is frequently missing on metric documents.

9. pull\_metric\_seeds(db, cfg) (STEP 2\) — runs a MongoDB aggregation ($match on date range \+ non-empty metric\_value, $sample for random oversampling, $project to trim fields) to pull a random sample of metric documents, extracts the hourly Average/Sum values via extract\_hourly\_values(), discards documents with fewer than 3 non-null/non-zero hourly readings, tags each with its detected cloud provider, and caps the result to cfg\['max\_resources'\] unique entities.

10. pull\_alert\_anchors(db, cfg) (STEP 3\) — separately queries the alerts collection for 'monitoring' alerts in the same date window and builds a dict of {resource\_id: \[(timestamp, 'spike'|'recovery'), ...\]}. These are strictly used later as anomaly injection points, not as ground-truth labels for supervised learning (there is none — this is self-supervised contrastive pretraining).

11. interpolate\_to\_minutes(...) (STEP 4a) — takes the 24 hourly values for one (entity, day, metric) seed row, fills any missing hours via linear interpolation, then fits a periodic cubic spline (CubicSpline with wrap-around boundary points) across the 24 hours and evaluates it at 1-minute resolution (1440 points), adding small Gaussian noise scaled to noise\_fraction so the curve isn't perfectly smooth.

12. inject\_anomalies(...) (STEP 4b) — for each entity, looks up any alert anchors that fall within that day's minute range, opens a random-duration window (15–45 minutes) around each anchor, and multiplies the value inside that window by a spike factor (3×–6×) or a drop factor (0.05×–0.2×) depending on whether the alert was a 'firing' or 'recovery' transition; also stamps is\_anomaly=True/anomaly\_type on those rows.

13. build\_corpus(...) (STEP 5\) — the main loop: iterates every seed row, calls interpolate\_to\_minutes then inject\_anomalies, attaches the entity/metric metadata columns, and concatenates all the resulting per-day DataFrames into one big corpus DataFrame with a fixed column order.

14. write\_output(...) (STEP 6\) — writes the corpus to Parquet (snappy compression) and a JSON summary alongside it.

15. generate\_synthetic\_seeds(...) / generate\_synthetic\_anchors(...) (FALLBACK) — if the MongoClient() connection fails or returns an empty seed set, the script switches to these functions instead, which hand-craft nine realistic 'archetypes' (AWS EC2, Azure VM, Azure Private Endpoint, OCI connector, etc.) with business-hours or always-on daily traffic shapes, so the rest of the pipeline still has something to chew on.

## **Key Code Sections**

* detect\_cloud() — the cloud-provider classifier. If your team ever sees an unexpectedly high 'Unknown' fraction in a run, this is the function to extend (the script even prints a warning when Unknown exceeds 30%).

* interpolate\_to\_minutes() — the core signal-synthesis routine; this is what actually manufactures believable minute-level noise from sparse hourly data using cubic spline interpolation.

* inject\_anomalies() — this is the ONLY place anomaly labels exist anywhere in the corpus; is\_anomaly/anomaly\_type are for post-hoc evaluation only, since the downstream encoder trains without any labels.

## **Why This File Matters**

Without this script, there is no historical corpus at all — every downstream file (augmentation, dataset streaming, encoder training) has nothing to read. It's also the only place in the whole pipeline where 'ground truth' anomaly information is created, which matters later if/when your team wants to sanity-check the trained encoder by checking whether embeddings of is\_anomaly=True windows land further from an entity's centroid than normal windows.

## **Watch-Outs / Notes**

| Schema note (important) This script's output schema — entity\_id, cloud, namespace, metric\_name, timestamp, value, one metric per row — already matches the CURRENT event-based schema used by streaming\_aug\_pairs\_dataset.py and tstcc\_encoder.py (metric\_name as a categorical column, value as a single numeric reading). This is good news: generate\_corpus.py does NOT need to change for the Phase 1 redesign. However, it does not itself produce pair\_id / view columns — that only happens in the augmentation step. See the mismatch flagged under generate\_aug\_pairs.py below. |
| :---- |

* The MongoDB connection block in main() uses a bare 5-second serverSelectionTimeoutMS and a broad except Exception — if you ever want to distinguish 'wrong URI' from 'auth failure' from 'network unreachable', you'll need to inspect the exception message printed to console.

* noise\_fraction (5% default) and anomaly multipliers are hardcoded in CONFIG rather than shared/config.yaml — worth migrating into config.yaml per your project's own convention once this script is finalized, so it participates in the same 'never hardcode values' rule documented in Section 2d of the Directory Structure.

# **4\. vm\_augmentation.py**

| Module Mapping | P1-M2 (Augmentation Pairs) — ORIGINAL PLAN, now superseded. This is the pre-redesign, map-style implementation that assumed a fixed 6-metric VM schema. |
| :---- | :---- |
| **Role in Pipeline** | A self-contained PyTorch Dataset (VMContrastiveDataset) that loads a small VM-telemetry Parquet file entirely into memory and, for every row, produces two independently-augmented tensor views (Temporal Jitter \+ Attribute Masking) for NT-Xent training. |
| **Status** | **Superseded / legacy — logic reused as a fallback import inside generate\_aug\_pairs.py, but the Dataset class itself is not used by the current training pipeline** |

## **Purpose**

This is the original augmentation module, written before the Phase 1 Architecture Addendum. It assumes every 'entity' is a VM emitting exactly six fixed numeric sensors (cpu\_usage, memory\_usage, disk\_io\_read, disk\_io\_write, net\_throughput\_in, net\_throughput\_out) plus three protected categorical identity columns (vm\_role, region, os\_type). For each source row it manufactures two augmented views to form a contrastive positive pair, following the same intuition documented in the module docstring: temporal jitter teaches the model that small time shifts don't change behavioral meaning, and attribute masking teaches robustness to missing sensors.

## **Inputs**

* A Parquet file path or a pre-loaded pandas DataFrame with columns: timestamp, the six numeric\_cols, and the three protected\_cols (vm\_role, region, os\_type).

* An AugmentationConfig dataclass controlling jitter range (1–5 minutes), mask ratio range (10%–30% of numeric columns), the mask fill value (0.0), and time2vec\_dim (8).

## **Outputs**

* Per \_\_getitem\_\_(idx) call: a tuple (view\_1, view\_2) of two 1-D float32 tensors, each of length (6 numeric cols × 2 \[value \+ mask flag\]) \+ 2 (hour\_of\_day, day\_of\_week) \+ 8 (time2vec) \= 22 dimensions.

* Via a DataLoader: batched tensors of shape (batch\_size, 22\) for each view.

## **How It Works — Step by Step**

16. time2vec(t, dim) / extract\_time\_features(ts, dim) — converts a timestamp into a fractional hour, a day-of-week integer, and a Time2Vec vector (one linear trend term \+ sine terms at increasing frequency), matching the same Time2Vec formulation later reused inside tstcc\_encoder.py's dedicated Time2Vec module.

17. apply\_temporal\_jitter(record, config) — copies the record, shifts its timestamp by a random ±1–5 minute delta, and recomputes hour\_of\_day/day\_of\_week/time2vec from the shifted timestamp so the augmentation is reflected consistently in every derived feature.

18. apply\_attribute\_masking(record, config) — copies the record, randomly selects 10–30% of the six numeric\_cols, zeroes them out, and sets a companion \*\_masked flag to 1.0 for masked columns (0.0 otherwise) so the model can, in principle, distinguish 'observed zero' from 'missing'.

19. record\_to\_tensor(record, config) — flattens a record dict into the final ordered 1-D tensor: \[metric, mask\_flag\] pairs for each of the 6 numeric columns, then hour\_of\_day, day\_of\_week, then the 8 Time2Vec values. Categorical identity columns (vm\_role/region/os\_type) are deliberately excluded here — the docstring notes they should go through nn.Embedding layers in the encoder instead, passed separately.

20. VMContrastiveDataset.\_\_getitem\_\_(idx) — applies apply\_temporal\_jitter then apply\_attribute\_masking twice, independently, to the same base record, producing two different augmented tensors for the same underlying reading — this is the actual (view\_1, view\_2) contrastive pair.

21. The if \_\_name\_\_ \== '\_\_main\_\_' block at the bottom is a self-contained smoke test: it fabricates 500 synthetic VM rows, builds the dataset, checks tensor shapes and dimensionality, verifies that two calls to the same index produce DIFFERENT tensors (proving the augmentation is genuinely stochastic, not cached), and runs one DataLoader batch.

## **Key Code Sections**

* time2vec() — the reference implementation of the Time2Vec formula that the production encoder's dedicated Time2Vec nn.Module (in tstcc\_encoder.py) reimplements as a learnable layer instead of this fixed/deterministic version.

* VMContrastiveDataset.\_\_getitem\_\_() — the single most important method: this is where the 'positive pair' concept that NT-Xent loss depends on is actually created.

## **Why This File Matters**

Even though its Dataset class isn't wired into the current training run, this file matters for two reasons: (1) it's the design reference generate\_aug\_pairs.py imports from when available, so its function signatures define the augmentation contract used by that script, and (2) the reasoning in its docstring (why jitter, why masking) is the conceptual basis the team's newer, event-based augmentation still relies on — only the schema assumption (6 fixed VM metrics) changed, not the underlying idea.

## **Watch-Outs / Notes**

| This is legacy/pre-redesign code Per the Phase 1 Architecture Addendum, the assumption of six fixed, always-present VM metrics does not hold across a real multi-cloud fleet (an Azure Storage account emits a completely different metric set than a VM). This file's numeric\_cols list and record\_to\_tensor() layout reflect the OLD wide-format schema, not the event-based metric\_name/value schema your team redesigned around. Do not wire VMContrastiveDataset directly into train\_tstcc.py — it is incompatible with the current TstccEncoder input contract (3 numeric \+ 4 categorical, event-based). It is safe to keep as reference/fallback logic only. |
| :---- |

# **5\. generate\_aug\_pairs.py**

| Module Mapping | P1-M2 (Augmentation Pairs) — the pair-file WRITER. In directory-structure terms this plays the role the original plan called 'PairGenerator', producing a static aug\_pairs.parquet file. |
| :---- | :---- |
| **Role in Pipeline** | Streams a source Parquet corpus row-group by row-group (never loading the whole file), applies two independent augmentations per source row, and writes a doubled-length aug\_pairs.parquet with pair\_id/view columns — all while keeping peak memory around 50-85MB regardless of source file size. |
| **Status** | **Functionally complete, but SCHEMA MISMATCH with the current pipeline — see Watch-Outs** |

## **Purpose**

This script exists purely to solve a memory problem: turning a 10–50GB corpus into a 2×-larger augmented-pairs file without ever holding more than one small batch in RAM at a time. It reuses (or falls back to reimplementing) the jitter/masking logic from vm\_augmentation.py, but wraps it in a streaming read → augment → write loop driven directly off PyArrow's row-group API, so it can run on a machine as small as a laptop even against a very large source file.

## **Inputs**

* **\--src** path to a source Parquet file — intended to be pretrain\_corpus.parquet from generate\_corpus.py.

* **\--batch-size** rows processed per augmentation call (default 10,000).

* **\--pairs-per-row** how many (a,b) pairs to generate per source row (default 1; NT-Xent only needs 1).

* Jitter/mask hyperparameters (--jitter-min/max, \--mask-min/max, \--time2vec-dim, \--seed), all forwarded into an AugmentationConfig.

## **Outputs**

* \--dst path — a Parquet file with 2 × pairs\_per\_row × (source row count) rows. Every source row produces exactly one view='a' row and one view='b' row sharing the same pair\_id. Columns: the augmented numeric columns, protected identity columns, hour\_of\_day, day\_of\_week, time2vec\_0..time2vec\_7, pair\_id (int64), view (string 'a'/'b').

## **How It Works — Step by Step**

22. The top of the file tries to import AugmentationConfig, apply\_temporal\_jitter, apply\_attribute\_masking, extract\_time\_features from vm\_augmentation.py; if that import fails (module not on the Python path), it falls back to an inline, functionally-identical copy of the same logic so the script is self-contained.

23. generate\_pairs(src, dst, config, ...) opens the source file as a pq.ParquetFile (metadata only — this does not load data yet) and logs total row/row-group counts.

24. For each row group: read\_row\_group(rg\_idx) loads just that row group into a PyArrow Table, converts to pandas, parses timestamps once, then chunks the row group into config.batch\_size-row pieces.

25. \_augment\_batch(df, config, global\_row\_offset, pairs\_per\_row) — for every row in the chunk, and for each of pairs\_per\_row repetitions, it independently augments the SAME base row twice (once per view), assigns a pair\_id computed from a running global\_row\_offset (so pair IDs stay globally unique even though data is processed in disjoint batches), flattens the Time2Vec list into 8 scalar columns, and appends both view rows to an output list — which is then converted to a DataFrame in one shot (explicitly avoiding repeated pd.concat/append calls, which would be quadratic-time).

26. On the very first chunk, \_infer\_output\_schema(sample\_df) builds a fixed PyArrow schema (forcing all numeric/time2vec columns to float32 to halve storage), and a pq.ParquetWriter is opened once and kept open across the entire run.

27. Each augmented chunk is cast to that fixed schema and written via writer.write\_table(), then immediately deleted (del \+ gc.collect()) before moving to the next chunk — this is the crux of the memory-safety design.

28. At the end, the writer is closed and a final summary (rows written, elapsed time, output file size, final RSS memory) is logged.

## **Key Code Sections**

* \_augment\_batch() — the actual pair-construction logic; this is where 'one source row becomes two matched rows' happens.

* generate\_pairs() main loop — study this if you ever need to adapt the same streaming pattern for a different transform (this is literally the same architecture streaming\_aug\_pairs\_dataset.py later uses for reading, just applied to writing).

* \_infer\_output\_schema() — worth knowing about because it silently coerces every non-identity column to float32; if you ever add a new integer ID column here it will be (probably harmlessly) cast to float.

## **Why This File Matters**

Without a script like this, the team would have to choose between loading a 10-50GB corpus fully into RAM (infeasible on most laptops) or writing pairs on-the-fly during training (which the team explicitly moved away from in the redesign — see the Directory Structure's note that StreamingAugPairsDataset now expects augmentation to already be 'baked into aug\_pairs.parquet's pair\_id/view columns upstream'). This script is exactly that upstream baking step.

## **Watch-Outs / Notes — Important Schema Mismatch**

| This script currently targets the OLD wide VM schema, not the event-based schema your pipeline now expects generate\_aug\_pairs.py's fallback AugmentationConfig.numeric\_cols defaults to an empty placeholder (\[...\]) and its imported version (from vm\_augmentation.py) hardcodes the six wide VM columns (cpu\_usage, memory\_usage, disk\_io\_read, disk\_io\_write, net\_throughput\_in, net\_throughput\_out). generate\_corpus.py, however, now outputs LONG/event-based rows (one metric\_name \+ value per row, not six wide columns). Feeding generate\_corpus.py's pretrain\_corpus.parquet directly into this script as \--src will NOT produce sensible output, because none of the six hardcoded numeric\_cols exist in that file, and this script has no metric\_name/value handling at all. streaming\_aug\_pairs\_dataset.py (the CURRENT consumer, described next) expects aug\_pairs.parquet to already contain entity\_id, timestamp, view, pair\_id, metric\_name, value, cloud, entity\_type, namespace, hour\_of\_day, day\_of\_week — a schema this script does not produce. Conclusion: this uploaded version of generate\_aug\_pairs.py appears to be an earlier iteration, from before the event-based redesign. The aug\_pairs.parquet actually used by your current training run (per train\_tstcc.py / streaming\_aug\_pairs\_dataset.py) must have been produced by an updated, event-based version of this script that hasn't been uploaded here. This is worth confirming with whoever owns P1-M2 (Member A) — see the Open Items section for the recommended fix. |
| :---- |

* Minor code smell: the fallback AugmentationConfig dataclass in this file has @dataclass stacked twice (decorator applied twice) — harmless but worth cleaning up.

* Minor: AugmentationConfig.numeric\_cols default is field(default\_factory=lambda: \[...\]) — a literal Ellipsis-in-a-list placeholder, not a real column list. If this fallback path is ever hit for real training data, masking will silently no-op because there are no real numeric columns to sample from.

# **6\. validate.py**

| Module Mapping | P1-M2 (Augmentation Pairs) — QA / smoke-test utility, not part of the training path itself. |
| :---- | :---- |
| **Role in Pipeline** | A short, standalone sanity-check script that samples ONE row group from aug\_pairs.parquet and runs four structural assertions before anyone trusts the file for a multi-hour training run. |
| **Status** | **Utility script — run manually / ad hoc, not imported by anything else** |

## **Purpose**

Training runs against aug\_pairs.parquet take hours. This script is the cheap, fast (single row-group, \~20K rows) check that catches the most common ways an augmentation pipeline can silently produce garbage: broken pairing, no actual jitter, corrupted mask flags, or unexpected nulls — all before you commit GPU time to a bad file.

## **Inputs**

* aug\_pairs.parquet (hardcoded relative path in the script) — reads only pf.read\_row\_group(0) via PyArrow, i.e. a fast partial read, not the full file.

## **Outputs**

* Console output only: a series of ✓/✗ print statements and, for the mask-flag and null checks, either a pass message or a printed table of the offending values/columns.

* Raises an AssertionError (crashes the script) if pair integrity or view-completeness checks fail — this is intentional; you want a hard stop, not a warning, if pairing is broken.

## **How It Works — Step by Step**

29. Loads exactly one row group with pf.read\_row\_group(0).to\_pandas() — deliberately avoids loading the full (potentially 17M-row) file.

30. Pair integrity check — groups by pair\_id and asserts every pair\_id appears exactly twice (counts \== 2).all(), and that the two rows per pair\_id are exactly {'a', 'b'} (views \== {'a', 'b'}).all(). This catches any bug in the writer that might drop a view or duplicate one.

31. Timestamp jitter check — splits into view-a and view-b frames indexed by pair\_id, computes the absolute timestamp difference per pair, and prints the mean difference (not asserted — this is a manual sanity read: if it printed \~0 seconds, jitter isn't actually happening).

32. Mask flag check — for every column ending in \_masked, asserts its value set is a subset of {0.0, 1.0} (catches float rounding bugs or accidental non-binary values).

33. Null check — sums nulls per column and either prints '✓ No nulls' or a breakdown of which columns have how many.

34. Finally prints df.dtypes so you can eyeball whether every column landed as the type you expect (e.g. catching an accidental object/string dtype on what should be float32).

## **Key Code Sections**

* counts \= df.groupby('pair\_id')\['view'\].count() — this one line is the most important correctness guarantee in the whole augmentation stage: if this assertion ever fails, nothing downstream (windowing, encoder training) can be trusted.

## **Why This File Matters**

It's cheap insurance. A silent pairing bug (e.g. two 'a' views and zero 'b' views for some entities) wouldn't necessarily crash training — StreamingAugPairsDataset would just silently produce fewer or malformed windows for the affected entities, and you might not notice until loss curves look strange days into training. This script turns that into an immediate, loud failure.

## **Watch-Outs / Notes**

* Only checks row group 0 — if a corruption is localized to a later row group (e.g. a bug that only manifests for a specific resource type processed later in the file), this script won't catch it. Worth extending to sample a few row groups (e.g. first, middle, last) rather than always row group 0\.

* This script assumes the OLD wide-format schema too — it checks generic \*\_masked columns and a timestamp column directly, which is compatible with either schema, but it has no awareness of metric\_name/value at all, so it would not catch event-based-schema-specific problems (e.g. a metric\_name that fails to map through the vocabulary). Consider adding an event-based validation pass once the updated aug\_pairs writer is in place.

# **7\. streaming\_aug\_pairs\_dataset.py**

| Module Mapping | P1-M2 — StreamingAugPairsDataset. This IS the current, as-built P1-M2 module referenced throughout the Phase 1 Architecture Addendum. Lives at phase1/data/streaming\_aug\_pairs\_dataset.py. |
| :---- | :---- |
| **Role in Pipeline** | The production PyTorch IterableDataset that turns aug\_pairs.parquet into batched, event-based (view\_a, view\_b) training windows for the encoder, without ever loading the full 17.9M-row file into memory. |
| **Status** | **Complete and current — this is the design of record, superseding both vm\_augmentation.py and the map-style AugPairsDataset mentioned in its own docstring** |

## **Purpose**

This is the module that actually feeds the encoder during training. Its defining design decision — explained at length in its own module docstring — is treating every row of aug\_pairs.parquet as a single (timestamp, metric\_name, value) reading EVENT rather than assuming a fixed wide schema of named metric columns. This was a direct response to discovering that different cloud resource types (a VM vs. an Azure Storage account) simply don't share a common metric set. It also solves the same memory problem generate\_aug\_pairs.py solves on the write side, but on the read side: it streams the file row-group by row-group as an IterableDataset instead of loading everything into a pandas DataFrame.

## **Inputs**

* aug\_pairs.parquet — expected to physically contain these columns: entity\_id, timestamp, view ('a'/'b'), pair\_id, metric\_name, value, cloud, entity\_type, namespace, hour\_of\_day, day\_of\_week (see AUG\_REQUIRED\_COLS).

* StreamingDatasetConfigData — a dataclass bundling: the parquet path, pre-computed vocab\_maps\_dict (from compute\_vocab\_sizes), pre-computed metric\_value\_stats\_dict (from compute\_metric\_value\_stats), seq\_len\_int (window length in EVENTS, default 32), stride\_int (window step, default 16), and a shuffle flag.

## **Outputs**

* Per iteration: a tuple of two dicts, each shaped {'numeric': Tensor(seq\_len, 3), 'categorical': Tensor(seq\_len, 4), 'timestamps': Tensor(seq\_len, 1)} — one for view\_a, one for view\_b of the same sliding window.

* After contrastive\_collate\_fn: batched tuples (numeric, categorical, timestamps) with shapes (B, seq\_len, 3), (B, seq\_len, 4), (B, seq\_len, 1\) for each view — this is exactly what TstccEncoder.forward() expects as its three positional arguments.

## **How It Works — Step by Step**

35. compute\_vocab\_sizes(parquet\_path) — a full-file, column-projected pass (only reads cloud/entity\_type/namespace/metric\_name columns, not all 31\) that builds a {label: index} dict per categorical column, reserving index 0 for PAD/UNK. This MUST be computed from the full file, not a sample, because metric\_name cardinality genuinely varies by resource type across row groups.

36. compute\_metric\_value\_stats(parquet\_path) — another full-file, column-projected pass (only metric\_name and value) that computes per-metric-name (mean, std) using an accumulate-sum / sum-of-squares approach across row groups (so it never holds more than one row group's worth of data at once), floors std at AUG\_VALUE\_NORM\_EPS to avoid divide-by-zero on constant-valued metrics.

37. StreamingAugPairsDataset.\_\_init\_\_ — deliberately does NOT open and store a pyarrow.parquet.ParquetFile handle on self; it only opens one transiently to read num\_row\_groups, then discards it. This is the fix for the 'Windows Multiprocessing Pickling' risk documented in the Team Planner's Risk Register — an open ParquetFile object can't be pickled, which would otherwise crash DataLoader(num\_workers\>0) on Windows.

38. \_get\_parquet\_file() — lazily opens (and caches) a ParquetFile handle the FIRST time it's actually needed, which happens separately inside each worker process (after any pickling/forking has already occurred), so every process gets its own safe handle.

39. \_\_iter\_\_ — checks get\_worker\_info(): with no workers, iterates all row groups; with N workers, shards row groups round-robin (worker i handles row groups i, i+N, i+2N, ...) so the file is read once total across all workers, not once per worker.

40. \_process\_row\_group(rg\_idx) — the real work, per row group: (a) reads only the required columns, (b) parses timestamps to UTC, (c) computes value\_norm \= (value \- per\_metric\_mean) / (per\_metric\_std \+ eps) using the GLOBAL stats passed in (never row-group-local stats, which would drift batch to batch), (d) normalises hour\_of\_day/day\_of\_week into \[0,1), (e) maps all 4 categorical columns through the global vocab maps into integer indices, (f) splits into view='a' and view='b' sub-frames, (g) groups each by entity\_id and sorts by (pair\_id, timestamp, metric\_name) so both views stay aligned event-for-event, (h) builds a list of (entity\_id, window\_start) sliding-window index tuples for every entity with enough matched rows, (i) optionally shuffles that window list, and (j) yields each window's rows\_a/rows\_b sliced from the pre-sorted per-entity frames.

41. \_rows\_to\_seq\_dict(rows, enc\_cat\_cols) — converts a slice of the DataFrame into the three tensors (numeric, categorical, timestamps) that make up one window's contribution to a batch, computing a normalised fractional-hour-of-day value directly from the timestamp column for the timestamps tensor.

42. contrastive\_collate\_fn(batch) — the DataLoader's collate\_fn: stacks a list of (seq\_a\_dict, seq\_b\_dict) tuples into two batched (numeric, categorical, timestamps) tuples. Because every window is already fixed-length (seq\_len\_int), no padding logic is needed here.

## **Key Code Sections**

* compute\_vocab\_sizes() / compute\_metric\_value\_stats() — the two functions that MUST run once, globally, before training starts; train\_tstcc.py calls both of these before it even constructs the encoder, because the encoder's vocabulary-sized embedding tables depend on their output.

* \_process\_row\_group() — the heart of the file; if you ever need to change how windows are built (e.g. different window semantics, different sort order), this is the only method you need to touch.

* StreamingAugPairsDataset.\_\_init\_\_ and its inline comment block — required reading if you ever touch this class, since it explains a genuinely non-obvious cross-platform bug (Windows 'spawn' pickling vs. Linux 'fork') that the current design deliberately avoids.

## **Why This File Matters**

This is the file that makes training on the full 17.9M-row corpus possible on a normal development machine at all — without it, the team would be stuck either subsampling the corpus (losing behavioral diversity) or hitting out-of-memory errors. It's also the single source of truth for the event-based schema; every other file that produces or consumes aug\_pairs.parquet (the writer, the encoder, train\_tstcc.py) must agree with the column names and semantics defined here.

## **Watch-Outs / Notes**

* Per its own docstring: sequence windows are only built from rows within the SAME row group. An entity whose events straddle a row-group boundary loses at most a handful of windows at that boundary — an accepted, documented trade-off, not a bug.

* seq\_len now means consecutive EVENTS (interleaved across whatever metrics an entity emits), not consecutive TIMESTAMPS — if an entity emits \~7 metrics per timestamp, a 32-event window covers roughly 4-5 timestamps of wall-clock history, which is a very different quantity than it sounds like at first glance. Worth being deliberate about \--seq-len choices in train\_tstcc.py with this in mind.

* This file is the ground truth for the exact input schema that generate\_aug\_pairs.py needs to produce — reconciling that mismatch (see the previous section) should treat AUG\_REQUIRED\_COLS here as the target schema to write towards.

# **8\. tstcc\_encoder.py**

| Module Mapping | P1-M3 — TstccEncoder (Contrastive Encoder). Lives at phase1/models/tstcc\_encoder.py. This is the single most important file in the codebase: the actual neural network being trained. |
| :---- | :---- |
| **Role in Pipeline** | Defines the full TSTCC (Time-Series representation learning via Temporal and Contextual Contrasting) architecture: EmbeddingLayer → Time2Vec → GRU → AttentionPooling → ProjectionHead, producing 128-dimensional, L2-normalised embeddings from a window of telemetry events. Same class is reused, unmodified, for both Phase 1 training and Phase 2 inference (P2-M3/P2-M4). |
| **Status** | **Complete, redesigned for the event-based schema, currently mid-training** |

## **Purpose**

This file is the model. Everything upstream (corpus generation, augmentation, streaming dataset) exists to feed this network; everything downstream in Phase 2 exists to consume its output. Its job is to take a window of raw, mixed-type telemetry (some numeric readings, some categorical tags, one timestamp per event) and compress it into a single fixed-size vector that captures 'what kind of behavior is this' in a way that's comparable via cosine similarity — which is exactly what P2-M7 (Cosine Distance) and P2-M9 (Episode Retrieval) need downstream.

## **Inputs (to TstccEncoder.forward())**

* numeric\_input\_tensor — shape (batch, seq\_len, 3): the z-scored value\_norm, plus normalised hour\_of\_day and day\_of\_week.

* categorical\_input\_tensor — shape (batch, seq\_len, 4): integer vocabulary indices for cloud, entity\_type, namespace, metric\_name, in that exact order (the order IS the contract).

* timestamps\_tensor — shape (batch, seq\_len, 1): a single normalised timestamp scalar (fractional hour / 24\) per event, fed into the learnable Time2Vec layer.

* lengths\_tensor (optional) — shape (batch,): true (non-padded) sequence lengths, used for variable-length-sequence support via pack/pad\_padded\_sequence. Not needed when every window in a batch is the same fixed length, as is the case with the current fixed seq\_len\_int windows.

## **Outputs**

* A single tensor of shape (batch, 128\) — every row is L2-normalised (unit length), so cosine similarity between any two embeddings equals their raw dot product. This is a hard, load-bearing contract: NT-Xent loss (ntxent\_loss.py) and every Phase 2 similarity computation both assume this.

## **How It Works — Architecture Walkthrough**

43. EmbeddingLayer — one independent nn.Embedding per categorical column (so 'cloud' and 'metric\_name' each get their own learnable lookup table, sized per-column via a min(vocab\_size // 2, 32\) heuristic, floored at 4), plus a single nn.Linear → LayerNorm projection for the 3 numeric features into a comparable-magnitude space. All categorical embeddings and the numeric projection are concatenated, then passed through one more Linear → LayerNorm to reach the fixed ENC\_FEATURE\_DIM \= 256 output width.

44. Time2Vec — a small, LEARNABLE version of the Time2Vec formulation (unlike the fixed/deterministic version in vm\_augmentation.py): one linear trend term plus 7 sine terms with learnable frequency/phase, output width k=8. Uses small-Gaussian (σ=0.01) parameter initialisation deliberately — the docstring explains that a naive uniform init can produce frequencies high enough to sit in sin()'s flat gradient region and effectively 'die' during training.

45. Feature \+ time concatenation — the 256-d EmbeddingLayer output and the 8-d Time2Vec output are concatenated to form the 264-d GRU input at every timestep (ENC\_GRU\_INPUT\_DIM \= 256 \+ 8).

46. GRU — a 2-layer, hidden-size-128, unidirectional nn.GRU, built directly inside TstccEncoder.\_\_init\_\_ (not a separate class). Handles variable-length sequences via pack\_padded\_sequence/pad\_packed\_sequence in the private \_run\_gru() helper when a lengths\_tensor is supplied; otherwise runs as a plain dense GRU.

47. AttentionPooling — a single-head, Bahdanau-style additive attention layer that collapses the GRU's per-timestep hidden states into one context vector: project each hidden state through tanh(Linear(h)), score it against a learned query vector, softmax the scores (masking out any padded positions to \-inf first), then take the attention-weighted sum of hidden states. Chosen over simply taking the GRU's last hidden state because it lets the model learn WHICH timesteps in the window carry the most anomaly-relevant signal.

48. ProjectionHead — a 2-layer MLP (Linear(128→128) → ReLU → Linear(128→128)) applied ONLY during contrastive pre-training (standard SimCLR/MoCo practice — the projection head helps the contrastive loss without contaminating the actual representation quality). It is skipped at inference via use\_projection\_bool=False / disable\_projection().

49. Final L2 normalisation — applied unconditionally in forward(), regardless of whether the projection head ran, so the 'always L2-normalised' contract holds for both training and inference call paths.

## **Key Code Sections**

* TstccEncoder.forward() — the 7-step orchestration method; read this first, it's a clean map of the whole architecture in \~35 lines.

* encode\_without\_projection() — the convenience method Phase 2 (P2-M3, P2-M4) will call: temporarily flips use\_projection\_bool off, runs a no\_grad forward pass, then restores the previous flag state in a finally block so it never permanently mutates a shared encoder instance.

* save\_weights() vs. save\_checkpoint() — two different persistence methods with two different payloads. save\_weights() writes only {state\_dict, use\_projection\_bool, embed\_dim\_int, gru\_hidden\_int} — this is what produces tstcc\_encoder\_final.pt. save\_checkpoint() writes the same plus epoch\_int, optionally optimizer\_state\_dict and loss\_float — this is what produces tstcc\_encoder\_epoch\_0020.pt. This explains why the two .pt files you uploaded are different sizes (see the artifact sections below).

* build\_tstcc\_encoder\_for\_aug\_pairs() — the factory function train\_tstcc.py actually calls; it takes the 4 raw vocab nunique() counts, adds the \+1 PAD/UNK reservation internally, computes each column's embedding dimension via the min(vocab//2, 32\) heuristic, and assembles the full TstccEncoderConfigData before delegating to build\_tstcc\_encoder().

## **Why This File Matters**

This is the model your entire capstone is graded on producing. Every other file in Phase 1 exists to feed data into this file or to train it; every file in Phase 2 exists to consume what comes out of it. The fact that the SAME class, with a single boolean flag, serves both training (P1-M3/P1-M4) and inference (P2-M3/P2-M4) is a deliberate and important design choice — it guarantees the exact same forward-pass math is used everywhere the encoder appears, eliminating an entire class of train/inference skew bugs.

## **Watch-Outs / Notes**

* The module's own comment block explicitly warns: checkpoints trained under the OLD 14-numeric/3-categorical schema CANNOT be loaded into the current 3-numeric/4-categorical architecture — shape mismatch on the embedding and numeric-projection layers. Don't attempt to warm-start from any older .pt files.

* The build\_tstcc\_encoder\_for\_aug\_pairs() docstring notes: build with use\_projection\_bool=True, call load\_weights(), THEN call disable\_projection() for inference — building directly with use\_projection\_bool=False and loading a training checkpoint with strict=True will fail, since the checkpoint's state\_dict still contains the projection head's keys.

* Its own bottom-of-file CLI (\_run\_cli(), run via python tstcc\_encoder.py \--parquet ...) is a genuinely useful smoke test independent of the full training script — it computes vocab/stats from ONLY the sampled row group(s) (explicitly logged as not representative of the full file) and reports untrained positive/negative pair cosine similarities purely as a wiring sanity check, not a training result.

# **9\. ntxent\_loss.py**

| Module Mapping | P1-M4 — NTXentLossComputer (Contrastive Loss / NT-Xent / InfoNCE). Lives at phase1/losses/ntxent\_loss.py. |
| :---- | :---- |
| **Role in Pipeline** | Implements the symmetric NT-Xent (Normalized Temperature-scaled Cross-Entropy) contrastive loss — the objective function that actually trains TstccEncoder by pulling matched (view\_a, view\_b) embeddings together and pushing every other pair in the batch apart. |
| **Status** | **Complete** |

## **Purpose**

An encoder alone doesn't learn anything — it needs a loss function that tells it what 'good' embeddings look like. This file is that loss function. Under self-supervised contrastive learning, there are no ground-truth labels; instead, the loss defines 'good' as: embeddings of two augmented views of the SAME underlying window should be close together (in cosine-similarity terms), while embeddings of any other pair of windows in the same batch should be far apart. NT-Xent is the standard SimCLR-style formalisation of that idea.

## **Inputs (to NTXentLossComputer.forward())**

* z\_a — Tensor, shape (B, 128): L2-normalised embeddings for view\_a of B windows (TstccEncoder's output).

* z\_b — Tensor, shape (B, 128): L2-normalised embeddings for view\_b of the SAME B windows, index-for-index matched with z\_a.

* NTXentLossConfigData — a one-field config dataclass holding temperature\_float (softmax temperature; lower \= sharper contrast between positive and negative pairs; default here is 0.1).

## **Outputs**

* A single scalar Tensor — the mean contrastive loss across all 2B rows (both the a→b and b→a directions), ready for .backward().

## **How It Works — Step by Step**

50. Validate that z\_a.shape \== z\_b.shape and that batch\_size \>= 2 (you need at least one other sample in the batch to serve as a negative).

51. Concatenate the two views along the batch dimension: z\_all \= \[z\_a ; z\_b\], shape (2B, 128).

52. Compute the FULL pairwise similarity matrix in one matrix multiply: sim\_matrix \= (z\_all @ z\_all.T) / temperature, shape (2B, 2B). Because every row is already L2-normalised, this dot product IS the cosine similarity, just temperature-scaled.

53. Mask the diagonal (each sample's similarity with itself) to \-inf, so softmax later assigns it zero probability — a sample must never be considered its own 'positive' or 'negative'.

54. For row i, its correct positive is at column (i \+ B) mod 2B — i.e. if i is a view\_a index (0..B-1), its positive is the matching view\_b at i+B; if i is a view\_b index (B..2B-1), its positive is the matching view\_a at i-B. This one-liner encodes the entire 'which pairs are positive' logic.

55. Compute F.cross\_entropy(sim\_matrix, positive\_idx) — PyTorch's cross-entropy treats each row of sim\_matrix as a set of 2B-1 (after masking) class logits and positive\_idx as the correct class per row. This single call implements the full symmetric (both a→b and b→a) NT-Xent loss in one line.

## **Key Code Sections**

* positive\_idx\_tensor \= (torch.arange(two\_b) \+ batch\_size) % two\_b — the single cleverest line in the file; it's worth internalising this modular-arithmetic trick since it's exactly how SimCLR-style implementations universally express 'symmetric positive pairing' without an explicit loop.

* sim\_matrix\_tensor.masked\_fill(self\_mask\_tensor, float('-inf')) — the self-exclusion step; forgetting this is one of the single most common contrastive-loss bugs (the model would trivially learn to maximize similarity with itself).

## **Why This File Matters**

Without this loss, TstccEncoder has no training signal at all — you could run the forward pass forever and the weights would never move meaningfully. This is also the one piece of the pipeline whose correctness is hardest to eyeball from loss curves alone (a subtly wrong positive-index calculation would still produce a smoothly decreasing loss, just optimising the wrong objective) — which is why the collapse diagnostic mentioned in the Team Planner (checking that positive-pair similarity meaningfully exceeds negative-pair similarity) matters as an independent sanity check alongside watching the loss value.

## **Watch-Outs / Notes**

| Temperature value discrepancy across files This file's LOSS\_DEFAULT\_TEMPERATURE constant, and the default used when NTXentLossConfigData() is constructed with no arguments, is 0.1. train\_tstcc.py's CLI also defaults \--temperature to 0.1, consistent with this file. However, the Project Directory Structure's shared/constants.py registry (Section 2d) documents TRAIN\_TEMPERATURE \= 0.07 as the canonical NT-Xent temperature, marked \[UNCHANGED\] from the original plan. This is a real, currently-live inconsistency between the constants registry (0.07) and the actual code defaults (0.1) — worth resolving the same way the team is already tracking the TRAIN\_LR (1e-4 vs 3e-4) discrepancy. See the Open Items section. |
| :---- |

# **10\. train\_tstcc.py**

| Module Mapping | P1-M4 — train\_tstcc.py main(). Lives at phase1/train/train\_tstcc.py. Per the Directory Structure Addendum there is deliberately NO standalone TrainingLoop or CosineLrScheduler class — both are inlined here. |
| :---- | :---- |
| **Role in Pipeline** | The conductor script: wires together the vocab/stats computation, the encoder (P1-M3), the loss (P1-M4), the optimizer/scheduler, and the streaming dataset (P1-M2) into one runnable end-to-end training job over the COMPLETE aug\_pairs.parquet file, with periodic checkpointing. |
| **Status** | **Actively running — as of the addendum, at epoch 10 of 20** |

## **Purpose**

This is the single script your team actually runs to produce a trained model. Everything else in Phase 1 is a building block; this file is the assembly line that turns those blocks into model\_registry/tstcc\_encoder\_epoch\_XXXX.pt checkpoints and, eventually, tstcc\_encoder\_final.pt. It is a real, full training job — not a wiring test — meant to stream the entire aug\_pairs.parquet file epoch after epoch.

## **Inputs**

* \--parquet (required) — path to aug\_pairs.parquet.

* Training hyperparameters as CLI flags, each with a sensible default: \--epochs (20), \--batch-size (64), \--seq-len (32, in reading events), \--stride (16, 50% window overlap), \--lr (3e-4), \--temperature (0.1), \--num-workers (2), \--checkpoint-dir (model\_registry), \--resume (path to resume from), \--device (auto-detected cuda/cpu), \--log-every (50 batches), \--max-batches-per-epoch (optional cap for quick test runs).

## **Outputs**

* model\_registry/tstcc\_encoder\_epoch\_NNNN.pt — a full checkpoint (weights \+ optimizer state \+ epoch \+ loss) written every ENC\_CHECKPOINT\_FREQ (5) epochs, and always on the final epoch.

* model\_registry/tstcc\_encoder\_final.pt — weights only, written once at the very end of training via encoder.save\_weights().

* Console/log output: per-batch loss every \--log-every batches, per-epoch summary (average loss, batch count, elapsed time, current learning rate).

## **How It Works — Step by Step**

56. Device selection — auto-detects CUDA, falls back to CPU, respects an explicit \--device override.

57. Vocab \+ stats computation (Step 1\) — calls compute\_vocab\_sizes(args.parquet) and compute\_metric\_value\_stats(args.parquet) from streaming\_aug\_pairs\_dataset.py, ONCE, before any training happens. Both are full-file passes; the script logs how long each took and how many classes/metrics were found.

58. Encoder construction (Step 2\) — calls build\_tstcc\_encoder\_for\_aug\_pairs(...) with the 4 vocab sizes just computed, moves it to the selected device, and logs the total parameter count.

59. Loss / optimizer / scheduler setup (Step 3\) — constructs NTXentLossComputer(NTXentLossConfigData(temperature\_float=args.temperature)), an AdamW optimizer over all encoder parameters at args.lr, and a CosineAnnealingLR scheduler with T\_max=args.epochs (so the learning rate follows a cosine decay curve across the full training run, ending near zero at the last epoch).

60. Optional resume (still Step 3\) — if \--resume is given, loads a checkpoint's state\_dict into the encoder, restores optimizer state if present, and picks up start\_epoch\_int from the checkpoint's epoch\_int \+ 1\.

61. Dataset config (Step 4\) — builds one StreamingDatasetConfigData shared across all epochs (contains the pre-computed vocab\_maps\_dict and metric\_value\_stats\_dict so they are NOT recomputed every epoch).

62. Epoch loop (Step 5\) — for each epoch: constructs a FRESH StreamingAugPairsDataset instance (since it's a one-shot iterable) and a fresh DataLoader wrapping it with contrastive\_collate\_fn, num\_workers=args.num\_workers, and drop\_last=True (NT-Xent's positive-index math requires every batch to be the same size).

63. Inner batch loop — for each (batch\_a, batch\_b) pair: moves all 6 tensors (numeric/categorical/timestamps × 2 views) to the device, zeroes gradients, runs the encoder forward TWICE (once per view) to get z\_a and z\_b, computes loss\_fn(z\_a, z\_b), backpropagates, clips gradients to max\_norm=1.0, and steps the optimizer. Running loss is tracked and logged periodically.

64. End of epoch — steps the LR scheduler, guards against a pathological 0-batches epoch (logs an error and exits — this would indicate seq\_len/batch\_size don't fit the available data), logs the epoch summary, and calls encoder.save\_checkpoint(...) every ENC\_CHECKPOINT\_FREQ epochs or on the final epoch.

65. After all epochs — calls encoder.save\_weights(final\_path) once to produce the lightweight, optimizer-free tstcc\_encoder\_final.pt.

## **Key Code Sections**

* for epoch\_int in range(start\_epoch\_int, args.epochs \+ 1): — the outer epoch loop; note that a brand-new StreamingAugPairsDataset() is constructed inside the loop every epoch (line: dataset \= StreamingAugPairsDataset(dataset\_cfg)) rather than being reused, since IterableDatasets are naturally single-pass.

* torch.nn.utils.clip\_grad\_norm\_(encoder.parameters(), max\_norm=1.0) — the gradient-clipping call that guards the GRU against exploding gradients, as flagged as a watch-out in the Team Planner's P1-M4 section.

* if n\_batches\_int \== 0: ... sys.exit(1) — a defensive check worth knowing about: if your \--seq-len/--batch-size combination is too large for the entities present in a given row group, an epoch can silently produce zero batches; this line turns that into a loud, immediate failure instead of a confusing 'training ran but did nothing' outcome.

## **Why This File Matters**

This is the actual command your team runs (python \-m phase1.train.train\_tstcc \--parquet ...) to produce the deliverable the entire capstone's Phase 2 depends on. Its design choices directly reflect lessons already learned during the project: computing vocab/stats ONCE up front (not per epoch) exists specifically because per-metric normalization requires a stable, global reference; the fresh-dataset-per-epoch pattern exists because IterableDataset is single-pass; and the checkpoint-then-final-weights split exists so a training crash mid-run never loses more than 5 epochs of progress.

## **Watch-Outs / Notes**

| Confirmed discrepancies already flagged by your own team, still visible in this script TRAIN\_LR: this script's \--lr default is 3e-4, matching the 'Confirmed Configuration' table in the Team Planner's P1-M4 section (which says the running job actually uses 3e-4), but the shared/constants.py registry in the Directory Structure still documents TRAIN\_LR \= 1e-4. Both docs already flag this as an open reconciliation item — it has not yet been resolved in either the code or the docs. Temperature: this script's \--temperature default is 0.1, which matches ntxent\_loss.py's own default, but does NOT match the shared/constants.py registry's TRAIN\_TEMPERATURE \= 0.07. Unlike the LR discrepancy, this one does not appear to be tracked anywhere yet — recommend adding it to the Risk Register / reconciliation list. |
| :---- |

* num\_workers defaults to 2 — combined with streaming\_aug\_pairs\_dataset.py's lazy-ParquetFile design, this should be safe on both Windows and Linux, but if you ever see the Windows pickling TypeError described in that file's docstring, the first thing to check is whether some other object got added to the Dataset's \_\_init\_\_ that isn't picklable.

* \--max-batches-per-epoch is a debug/quick-test knob only — leaving it unset (the default) is required for the 'real' full-file training run; a fast-debug CLI invocation using it is explicitly referenced in the Team Planner's Week 2 integration gate (python \-m phase1.train.train\_tstcc \--epochs 1 \--fast-debug), so keep that flag name and this one in sync if that debug flag gets added.

# **11\. tstcc\_encoder\_epoch\_0020.pt**

| Module Mapping | P1-M4 — training artifact, produced by TstccEncoder.save\_checkpoint() inside train\_tstcc.py's epoch loop. |
| :---- | :---- |
| **Role in Pipeline** | A binary PyTorch checkpoint capturing the FULL training state at epoch 20 — model weights, optimizer momentum/variance buffers, epoch number, and training loss — sized 4.1 MB. |
| **Status** | **Artifact (not source code) — inspect with torch.load(), don't try to open as text** |

## **What This File Actually Contains**

This is not a script — it's the serialized output of TstccEncoder.save\_checkpoint(epoch\_int=20, optimizer\_state\_dict=optimizer.state\_dict(), loss\_float=\<avg loss\>). Per save\_checkpoint()'s implementation in tstcc\_encoder.py, the file is a Python dict (saved via torch.save, which pickles it) containing exactly these keys:

* epoch\_int — 20

* state\_dict — every learnable parameter in the encoder: all 4 categorical embedding tables, the numeric projection Linear+LayerNorm, the output fusion Linear+LayerNorm, Time2Vec's linear/sine parameters, the 2-layer GRU's weight matrices, AttentionPooling's projection Linear and query vector, and the ProjectionHead's two Linear layers.

* use\_projection\_bool — True (training was still using the projection head at this point, as expected).

* embed\_dim\_int / gru\_hidden\_int — both 128, recorded for later verification when reloading.

* optimizer\_state\_dict — AdamW's per-parameter momentum (exp\_avg) and variance (exp\_avg\_sq) buffers. This is why this file is notably larger than tstcc\_encoder\_final.pt: AdamW roughly doubles-to-triples the storage footprint of the raw model weights, since it stores two extra tensors of the same shape as every trainable parameter.

* loss\_float — the average NT-Xent loss recorded across epoch 20's batches.

## **Why It Exists**

This is a RESUMABLE checkpoint, not just a snapshot. Because it includes the optimizer state, train\_tstcc.py's \--resume flag can load it and continue training with AdamW's momentum intact, rather than restarting optimization from a cold state (which would otherwise cause a visible loss spike right after resuming). Per your project's checkpoint cadence (every ENC\_CHECKPOINT\_FREQ \= 5 epochs), this is one of the periodic safety nets that means a crash mid-run never loses more than a few epochs of progress.

## **How to Inspect It Yourself**

import torch  
ckpt \= torch.load('tstcc\_encoder\_epoch\_0020.pt', map\_location='cpu')  
print(ckpt.keys())  
print('epoch:', ckpt\['epoch\_int'\], '  loss:', ckpt\['loss\_float'\])  
print('projection head active:', ckpt\['use\_projection\_bool'\])

# **12\. tstcc\_encoder\_final.pt**

| Module Mapping | P1-M4 — training artifact, produced by TstccEncoder.save\_weights() at the very end of train\_tstcc.py's main(). |
| :---- | :---- |
| **Role in Pipeline** | The FINAL, lightweight, deployment-oriented checkpoint — model weights ONLY, no optimizer state — sized 1.4 MB (noticeably smaller than the epoch-20 checkpoint for exactly this reason). |
| **Status** | **Artifact (not source code)** |

## **What This File Actually Contains**

Produced by save\_weights(final\_path), which writes a smaller dict than save\_checkpoint():

* state\_dict — the same set of learnable parameters as above.

* use\_projection\_bool — whatever the flag's value was at the moment training finished (True, since training keeps the projection head enabled throughout).

* embed\_dim\_int / gru\_hidden\_int — 128 / 128\.

* No epoch\_int, no optimizer\_state\_dict, no loss\_float — this file is not meant to resume training, only to load a finished model for use.

## **Why It Exists — and Why It's Smaller**

This is the file Phase 2 is actually meant to consume: P2-M3 (InferenceEncoder) and P2-M4 (ReferenceEncoderService) both call load\_weights() (not load\_state\_dict on a raw optimizer-laden checkpoint) and then disable\_projection() to strip the projection head before running inference. Leaving optimizer state out entirely is deliberate — it would be dead weight in a deployed inference service, roughly doubling or tripling the file size for information that inference never needs.

## **How to Inspect It Yourself**

import torch  
weights \= torch.load('tstcc\_encoder\_final.pt', map\_location='cpu')  
print(weights.keys())   \# state\_dict, use\_projection\_bool, embed\_dim\_int, gru\_hidden\_int  
print('num tensors in state\_dict:', len(weights\['state\_dict'\]))

| Sanity check before trusting this file Per tstcc\_encoder.py's own architecture-compatibility warning: this file should only ever be loaded into an encoder built with the SAME vocab sizes (cloud/entity\_type/namespace/metric\_name counts) used at training time. Loading it into a freshly-built encoder with different vocab sizes will fail on the categorical embedding table shapes. Since the Team Planner records training as still in progress at epoch 10/20 as of the addendum, double-check whether this specific tstcc\_encoder\_final.pt corresponds to a full 20-epoch cosine-annealed run, or an earlier/partial run saved under the same filename — the filename alone doesn't carry epoch provenance the way the epoch-numbered checkpoint does. If in doubt, prefer resuming from the numbered checkpoint (which does carry epoch\_int) over trusting this file's provenance blindly. |
| :---- |

# **13\. Open Items & Discrepancies Found**

Collected here in one place, in priority order, for a team triage pass. The first two were already known to your team (per the planning docs); the rest were found while reading the uploaded code against those docs.

## **1\. Schema mismatch: generate\_aug\_pairs.py / vm\_augmentation.py vs. the event-based pipeline**

Highest priority. generate\_aug\_pairs.py (and the vm\_augmentation.py logic it imports) hardcode a wide, 6-fixed-metric VM schema (cpu\_usage, memory\_usage, disk\_io\_read, disk\_io\_write, net\_throughput\_in, net\_throughput\_out). generate\_corpus.py's current output and streaming\_aug\_pairs\_dataset.py's expected input are both event-based (metric\_name \+ value per row, plus pair\_id/view). The uploaded generate\_aug\_pairs.py cannot correctly consume generate\_corpus.py's output as-is.

* Action: confirm with whoever owns P1-M2 whether an updated, event-based version of generate\_aug\_pairs.py already exists and simply wasn't uploaded, or whether the pair-generation step needs to be rewritten to emit pair\_id/view columns on top of the long-format corpus schema.

## **2\. TRAIN\_LR: 1e-4 (constants registry) vs. 3e-4 (train\_tstcc.py, Team Planner config table)**

Already tracked as an open reconciliation item in both planning documents. train\_tstcc.py's \--lr default of 3e-4 matches what the Team Planner says the running job is actually using. shared/constants.py still says 1e-4. Needs a decision \+ a single edit to bring both into agreement before P1-M5/P1-M6 begin, per the Directory Structure's own callout.

## **3\. NEW — Temperature: 0.1 (ntxent\_loss.py & train\_tstcc.py) vs. 0.07 (constants registry)**

Not yet tracked anywhere. Both ntxent\_loss.py's LOSS\_DEFAULT\_TEMPERATURE and train\_tstcc.py's \--temperature CLI default are 0.1, but shared/constants.py's TRAIN\_TEMPERATURE is documented as 0.07 and marked \[UNCHANGED\]. Recommend adding this to the same reconciliation note as the TRAIN\_LR item, and confirming which value the actual epoch-10 training run in progress is using (check the \--temperature value the run was launched with, or the encoder's checkpoint metadata if temperature is ever logged there).

## **4\. Minor: duplicate @dataclass decorator in generate\_aug\_pairs.py's fallback config**

Harmless but worth a quick cleanup — the fallback AugmentationConfig class has @dataclass applied twice in a row.

## **5\. Minor: placeholder numeric\_cols default in generate\_aug\_pairs.py's fallback config**

field(default\_factory=lambda: \[...\]) is a literal Ellipsis placeholder rather than a real column list. If this fallback path (used when vm\_augmentation.py isn't importable) is ever hit against real data, attribute masking will silently do nothing meaningful.

## **6\. Provenance: which run produced tstcc\_encoder\_final.pt?**

Since training was recorded as in-progress at epoch 10/20 in the Team Planner, worth double-checking that tstcc\_encoder\_final.pt corresponds to a completed 20-epoch run and not an earlier partial save reused under the same filename — the numbered checkpoint (tstcc\_encoder\_epoch\_0020.pt) carries epoch\_int provenance; the final-weights file does not.

# **14\. Summary**

All ten uploaded files sit entirely within Phase 1 of CAPSTONE-189, forming one continuous pipeline: MongoDB → generate\_corpus.py → (augmentation) → streaming\_aug\_pairs\_dataset.py → tstcc\_encoder.py \+ ntxent\_loss.py, orchestrated by train\_tstcc.py, producing the two checkpoint artifacts at the end. The core encoder architecture (tstcc\_encoder.py) and the current streaming dataset (streaming\_aug\_pairs\_dataset.py) are both fully aligned with the Phase 1 Architecture Addendum's event-based redesign. The main gap found is that the uploaded augmentation-pair generator (generate\_aug\_pairs.py) and its dependency (vm\_augmentation.py) still reflect the pre-redesign wide-schema assumption, and don't structurally line up with the corpus generator or the streaming dataset as uploaded — this is worth resolving first, since it's the one place where the pipeline as uploaded wouldn't actually run end-to-end without modification.

Keep this document alongside the Project Directory Structure and Team Planner docs — treat it as the 'what the code actually does today' companion to their 'what the plan says' role.