"""
shared/constants.py
====================
CAPSTONE-189  |  UPPER_SNAKE_CASE constants, grouped by module prefix.

Scope note
----------
Only the constants needed by P2-M1 (Ingestion) and P2-M2 (Encoding) are
defined here. The AUG_* / ENC_* values below are copied verbatim from the
as-built phase1/data/streaming_aug_pairs_dataset.py and
phase1/models/tstcc_encoder.py so that P2-M2 cannot silently drift from
the training-time preprocessing contract. If those two files are ever
updated, update the matching constants here in the same PR.
"""

# -- Ingestion (P2-M1) -------------------------------------------------
INGEST_BATCH_WIN_SEC: int = 300     # 5-minute batch window (configurable; 30s for demos)
INGEST_POLL_MS: int = 100           # Kafka/Kinesis/PubSub poll timeout per cycle

# -- Augmentation Pairs / Encoder Input (P1-M2, P1-M3, P2-M2) -----------
# Column order is the CONTRACT — must match streaming_aug_pairs_dataset.py's
# AUG_CATEGORICAL_COLS exactly, since TstccEncoder.EmbeddingLayer reads
# categorical_input_tensor[..., i] positionally, not by name.
AUG_CATEGORICAL_COLS: list[str] = ["cloud", "entity_type", "namespace", "metric_name"]
AUG_TIME_SCALAR_COLS: list[str] = ["hour_of_day", "day_of_week"]
AUG_NUMERIC_COLS: list[str] = ["value_norm"] + AUG_TIME_SCALAR_COLS  # = 3, order matters
AUG_PAIRS_NUM_NUMERIC: int = 3
AUG_VALUE_NORM_EPS: float = 1e-6    # floors per-metric std to avoid divide-by-zero

# -- Encoder (P1-M3, P2-M3, P2-M4) — for reference / vocab sizing only --
ENC_EMBED_DIM: int = 128
ENC_FEATURE_DIM: int = 256

# -- Reference encoder (P2-M4) ------------------------------------------
REF_HISTORY_DAYS: int = 90          # historical window encoded on (re)build
REF_HISTORY_LEN: int = 30           # max window-embeddings kept per entity
REF_CENTROID_ALPHA: float = 0.1     # EMA update factor for incremental refresh
REF_DRIFT_ALARM_STD: float = 3.0    # flag entity if new emb is > N std from centroid
REF_SEQ_LEN: int = 32               # events per window, matches P1-M3 training default

# -- Entity Store / Redis (P2-M6) — referenced by P2-M4 --------------------
REDIS_HISTORY_LEN: int = 30         # rolling history window (mirrors REF_HISTORY_LEN)


REDIS_EMB_BYTES = 128 * 2
