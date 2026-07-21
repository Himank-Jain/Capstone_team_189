# CAPSTONE-189 — Phase 0 (Layer 1)
## Adaptive Statistical Baseline & Anomaly Scoring — Project Directory Structure

**Scope note:** Phase 0 is architecturally and operationally independent of Phase 1 (offline TSTCC contrastive pretraining) and Phase 2 (online inference via learned embeddings). It shares no code, no learned weights, and no FAISS/entity-store infrastructure with Phases 1–2. It can run entirely on its own as a fast, lightweight, per-`(vm, metric)` statistical anomaly detector, and may later serve as either a standalone product or a first-pass filter feeding into the heavier Phase 2 pipeline. Nothing in this module imports from `phase1/`, `phase2/`, or `shared/`.

---

## 1. What Phase 0 Does (Recap)

For every `(vm_id, metric_name)` series, maintain a small, constantly-updating statistical "shape of the day" — one rolling mean/std (or median/MAD) per time bucket (e.g. per hour, optionally split weekday/weekend) — stored as tiny state records in Redis. Score each new reading by comparing it against the correct bucket's baseline (a z-score or robust z-score), flag if it exceeds a threshold, then incrementally update that bucket. No training, no model files, no GPU — just streaming arithmetic and O(1) Redis lookups, scaling to thousands of series at millisecond latency.

---

## 2. Project Directory Structure

```
phase0/                                   # Phase 0 - Adaptive Statistical Baseline (fully independent)
├── __init__.py
│
├── types.py                              # MetricPoint, BucketKey, BucketState, ScoreResult dataclasses
├── constants.py                          # UPPER_SNAKE constants - bucket config, thresholds, Redis key prefixes
│
├── bucketing/                            # Time-bucket resolution
│   ├── __init__.py
│   └── bucket_key_resolver.py            # class BucketKeyResolver
│
├── baseline/                             # Rolling statistical state, Redis-backed
│   ├── __init__.py
│   ├── welford_accumulator.py            # class WelfordAccumulator
│   ├── robust_stats_accumulator.py       # class RobustStatsAccumulator (median/MAD)
│   └── rolling_baseline_store.py         # class RollingBaselineStore
│
├── seasonality/                          # Per-metric bucketed-vs-global decision
│   ├── __init__.py
│   └── seasonality_classifier.py         # class SeasonalityClassifier
│
├── scoring/                              # Anomaly scoring logic
│   ├── __init__.py
│   ├── zscore_scorer.py                  # class ZScoreScorer
│   └── drift_adjuster.py                 # class ExponentialDecayAdjuster (optional long-term drift handling)
│
├── streaming/                            # Ingestion adapters (self-contained - NOT shared with Phase 2)
│   ├── __init__.py
│   ├── base_stream_reader.py             # class BaseStreamReader (ABC)
│   ├── kafka_stream_reader.py            # class KafkaStreamReader(BaseStreamReader)
│   └── redis_stream_reader.py            # class RedisStreamReader(BaseStreamReader)
│
├── workers/                              # Orchestration
│   ├── __init__.py
│   └── anomaly_scoring_worker.py         # class AnomalyScoringWorker
│
├── config/
│   └── phase0_config.yaml                # bucket granularity, window size, thresholds, Redis connection
│
├── scripts/
│   └── run_worker.py                     # CLI entry point: python -m phase0.scripts.run_worker
│
└── tests/
    └── unit/
        ├── test_bucket_key_resolver.py
        ├── test_welford_accumulator.py
        ├── test_robust_stats_accumulator.py
        ├── test_rolling_baseline_store.py
        ├── test_zscore_scorer.py
        └── test_anomaly_scoring_worker.py
```

---

## 3. Module-by-Module Reference

### 3.1 `types.py` — Shared Dataclasses

The integration contract for Phase 0, analogous in spirit to `shared/types.py` in Phases 1–2, but entirely self-contained within `phase0/`.

| Dataclass | Fields | Purpose |
|---|---|---|
| `MetricPoint` | `vm_id: str`, `metric_name: str`, `timestamp: datetime`, `value: float` | One raw incoming reading — the unit of work flowing through the stream. |
| `BucketKey` | `vm_id: str`, `metric_name: str`, `hour: int`, `is_weekend: bool` (or `None` for global fallback) | Uniquely identifies one rolling baseline. Doubles as the Redis key components. |
| `BucketState` | `count: int`, `mean: float`, `m2: float` (Welford's running sum of squared diffs), `window: deque[float]` (bounded, for sliding-window eviction) | The tiny piece of state held per bucket in Redis. `std` is derived from `m2`/`count`, not stored redundantly. |
| `ScoreResult` | `vm_id`, `metric_name`, `bucket_key`, `value`, `z_score: float`, `is_anomaly: bool`, `baseline_mean`, `baseline_std`, `scored_at: datetime` | Output of scoring one point — what gets published/alerted on. |

---

### 3.2 `bucketing/bucket_key_resolver.py`

**Role:** Turns a raw timestamp into the correct bucket key — the single place where "hour granularity," "weekday/weekend split," and "which bucket does this reading belong to" logic lives (SRP).

**Class: `BucketKeyResolver`**
- `resolve(vm_id, metric_name, timestamp) -> BucketKey` — derives `hour = timestamp.hour`, `is_weekend = timestamp.weekday() >= 5`.
- Configurable granularity (default: hourly, 48 buckets/week per series). Coarser granularity (e.g. 4-hour blocks) is a config change here only — nothing else in the system needs to know.

---

### 3.3 `baseline/welford_accumulator.py`

**Role:** Incremental mean/variance computation using **Welford's algorithm** — the reason the system never needs to store or rescan a full 30-day value list to get a mean/std; it updates in O(1) per point with numerically stable running sums.

**Class: `WelfordAccumulator`**
- `update(new_value: float) -> None` — folds in one new point, updates `count`, `mean`, `m2`.
- `remove(old_value: float) -> None` — the sliding-window counterpart: removes the value that just aged out (30 days old at this bucket), keeping the window exactly 30 points wide without ever holding all 30 raw values in the "pure" Welford path.
- `std` (property) — `sqrt(m2 / count)`.
- **Why both `update` and `remove` matter:** a naive Welford implementation only supports adding points forever (an expanding window). A true 30-day *rolling* baseline needs the removal counterpart too, which requires retaining the bounded value list (`BucketState.window`) purely so the value being evicted is known — this is why `BucketState` carries both the Welford sums *and* a bounded deque, not one or the other.

---

### 3.4 `baseline/robust_stats_accumulator.py`

**Role:** The median/MAD (median absolute deviation) alternative to mean/std, for metrics where a few extreme spikes would otherwise distort a mean-based baseline (e.g. bursty I/O metrics).

**Class: `RobustStatsAccumulator`**
- Maintains the bounded window explicitly (median/MAD have no O(1) incremental update like Welford's — this is an intentional, documented cost/accuracy tradeoff, not an oversight).
- `median` / `mad` (properties).
- `robust_z_score(value) -> float` — `0.6745 * (value - median) / mad` (the standard consistency-corrected robust z-score formula).

---

### 3.5 `baseline/rolling_baseline_store.py`

**Role:** The Redis-backed persistence layer — Information Expert for "what is this bucket's current state," and the only place that knows Redis key format.

**Class: `RollingBaselineStore`**
- `get_bucket_state(bucket_key: BucketKey) -> Optional[BucketState]` — O(1) fetch.
- `update_bucket(bucket_key: BucketKey, new_value: float) -> BucketState` — fetch, fold in new value via `WelfordAccumulator`/`RobustStatsAccumulator`, evict the oldest value if the window exceeds `WINDOW_SIZE_DAYS`, write back — all as one atomic Redis transaction (`MULTI`/`EXEC` or a Lua script) to avoid read-modify-write races under concurrent workers.

**Redis key schema:**
```
phase0:baseline:{vm_id}:{metric_name}:hour{HH}:{weekday|weekend}
    → Redis Hash: {count, mean, m2, window (serialized list)}
```
Example: `phase0:baseline:vm-042:cpu_utilization:hour03:weekday`

**Scale estimate:** 200 VMs × 15 metrics × 48 buckets ≈ 144,000 keys, ~200 bytes each ≈ well under 50MB total — trivial for a single Redis instance, matching the original design's own math.

---

### 3.6 `seasonality/seasonality_classifier.py`

**Role:** Decides, per `(vm_id, metric_name)`, whether bucketed (hourly/weekday-weekend) or a single global rolling baseline is appropriate — implements the "for metrics without time-of-day seasonality, fall back to a single global rolling baseline" requirement.

**Class: `SeasonalityClassifier`**
- `is_seasonal(vm_id, metric_name) -> bool` — either a config-driven allowlist/denylist per metric_name (simple, deterministic, recommended default) or, as a future enhancement, a statistical test (e.g. comparing within-bucket variance to across-bucket variance) run periodically offline.
- `AnomalyScoringWorker` consults this once per series (cached) to decide whether to resolve a full `BucketKey` or a metric-level-only global key.

---

### 3.7 `scoring/zscore_scorer.py`

**Role:** Pure scoring logic — SRP: this class only computes a score and a flag; it never touches Redis or the stream directly.

**Class: `ZScoreScorer`**
- `score(value: float, bucket_state: BucketState, threshold: float = 3.0) -> ScoreResult`
- Supports both standard z-score (mean/std) and robust z-score (median/MAD) via a strategy flag, so switching a metric's scoring method is a config change, not a code change (Protected Variations).

---

### 3.8 `scoring/drift_adjuster.py`

**Role:** Optional long-term trend handling — exponential decay weighting (recent points count more than older ones within the same bucket) or a periodic detrending step (e.g. nightly job that re-centers a bucket's baseline if a sustained shift is detected). Kept as a separate, optional module so the core scoring path works correctly without it — Phase 0's MVP can ship without this and add it later with no changes to `ZScoreScorer` or `RollingBaselineStore`.

---

### 3.9 `streaming/` — Ingestion Adapters

**Role:** Self-contained stream readers — deliberately **not** shared with Phase 2's `phase2/ingestion/` package, per the independence requirement. Same `BaseStreamReader` ABC pattern (LSP: `KafkaStreamReader`/`RedisStreamReader` are interchangeable), but a separate implementation so Phase 0 has zero import dependency on Phase 1/2 code.

- `base_stream_reader.py` — `BaseStreamReader(ABC)`: `start()`, `stop()`, `poll(timeout_ms) -> List[MetricPoint]`.
- `kafka_stream_reader.py` — reads from a Kafka topic partitioned by `(vm_id, metric_name)` (or a hash of it) so parallel consumers each own a disjoint slice of series, enabling the "runs in parallel with O(1) lookups per point" scaling claim.
- `redis_stream_reader.py` — alternative backend using Redis Streams directly (`XREAD`), useful if the team wants to avoid standing up Kafka just for this lightweight layer.

---

### 3.10 `workers/anomaly_scoring_worker.py`

**Role:** The Controller (GRASP) — orchestrates the full per-point cycle: read → resolve bucket → fetch baseline → score → flag/publish → update baseline. This is the class actually run in production, one instance per parallel partition.

**Class: `AnomalyScoringWorker`**
- Constructor takes an injected `BaseStreamReader`, `RollingBaselineStore`, `SeasonalityClassifier`, `ZScoreScorer` (DIP — testable with mocks/stubs for each).
- `run_forever()` / `run_async()` — the main loop: `poll()` → for each `MetricPoint`: resolve `BucketKey` (or global fallback per `SeasonalityClassifier`) → `get_bucket_state()` → `score()` → publish `ScoreResult` (to a log, a topic, or a callback) → `update_bucket()`.
- Never crashes on a single bad point — malformed points are logged and skipped, matching the same "never crash on bad events" principle used in Phase 2's `IngestionPipeline`.

---

### 3.11 `config/phase0_config.yaml`

All tunable values live here, never hardcoded (matching the rest of the project's "never hardcode values" convention):

```yaml
bucket_granularity_hours: 1        # 1 = hourly buckets (24/day); e.g. 4 = 6 buckets/day
split_weekday_weekend: true        # 24 buckets -> 48 if true
window_size_days: 30
zscore_threshold: 3.0
scoring_method: "zscore"           # "zscore" | "robust_zscore"
redis:
  host: "localhost"
  port: 6379
  key_prefix: "phase0:baseline"
kafka:
  bootstrap_servers: "localhost:9092"
  topic: "vm-metrics-stream"
  num_partitions: 8                 # parallelism factor
```

---

## 4. Naming Conventions (Consistent with Phase 1/2)

Reuses the same project-wide conventions already established for Phases 1–2, for consistency across the whole codebase even though Phase 0 is functionally independent:

| Suffix/Prefix | Meaning | Example |
|---|---|---|
| `...Resolver` | Maps one representation to another (SRP) | `BucketKeyResolver` |
| `...Accumulator` | Incremental/rolling stateful computation | `WelfordAccumulator`, `RobustStatsAccumulator` |
| `...Store` | Persists/retrieves keyed state | `RollingBaselineStore` |
| `...Classifier` | Categorical decision logic | `SeasonalityClassifier` |
| `...Scorer` | Computes a numeric score from inputs | `ZScoreScorer` |
| `...Adjuster` | Modifies an existing computed value | `ExponentialDecayAdjuster` |
| `...Reader` (streaming) | Read-only stream interface | `KafkaStreamReader` |
| `...Worker` | Background loop / orchestrator | `AnomalyScoringWorker` |
| `resolve_` / `compute_` / `score_` / `update_` | snake_case + verb prefix, same convention as Phase 1/2 constants/functions | `resolve_bucket_key()`, `compute_zscore()` |
| `UPPER_SNAKE` constants | Module-prefixed | `PHASE0_ZSCORE_THRESHOLD`, `PHASE0_WINDOW_SIZE_DAYS` |

---

## 5. Data Flow Summary

```
MetricPoint (vm_id, metric_name, timestamp, value)
        │
        ▼
BucketKeyResolver.resolve()  ──► BucketKey (or global fallback via SeasonalityClassifier)
        │
        ▼
RollingBaselineStore.get_bucket_state()  ──► BucketState (mean, std / median, mad)
        │
        ▼
ZScoreScorer.score()  ──► ScoreResult (z_score, is_anomaly)
        │
        ├──► published downstream (alerting, or as a Phase 2 pre-filter)
        │
        ▼
RollingBaselineStore.update_bucket()  ──► incorporates new value, evicts oldest
```

---

## 6. Explicit Non-Dependencies (Independence Guarantee)

To keep Phase 0 genuinely decoupled, as required:
- **No imports from `phase1/`, `phase2/`, or `shared/`.** Phase 0 defines its own `types.py`/`constants.py` rather than reusing `shared/types.py`.
- **No shared Redis keyspace with Phase 2's Dynamic Entity Store (P2-M6).** Phase 0 uses its own `phase0:baseline:*` key prefix; P2-M6 uses `entity:{id}:*`. They may run against the same physical Redis instance without collision, but never read/write each other's keys.
- **No shared Kafka topic with Phase 2's ingestion (P2-M1)**, unless explicitly wired together later as a deliberate integration (e.g. Phase 0 as a pre-filter feeding Phase 2) — that would be a future, opt-in integration point, not a default coupling.
