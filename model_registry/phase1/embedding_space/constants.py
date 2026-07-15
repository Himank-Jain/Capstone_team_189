"""
shared/constants.py  --  complete constant registry
=======================================================
Unified Predictive Analytics & Intelligent Alerting Platform  |  CAPSTONE-189

Single source of truth for ALL UPPER_SNAKE + ModulePrefix constants used
across phase1/ and phase2/. No module should hardcode a value that already
has an entry here (Section 2d, Project Directory Structure).

Per the Phase 1 Architecture Addendum: TRAIN_LR is flagged as an OPEN
RECONCILIATION ITEM below (documented 1e-4, but the addendum-era training
job used 3e-4). Confirm which is correct and update this file before
P1-M5/P1-M6 are considered final for this run.
"""

# -- Encoder (P1-M3, P2-M3, P2-M4) -----------------------------
ENC_EMBED_DIM        = 128    # output embedding dimensionality      [UNCHANGED]
ENC_FEATURE_DIM      = 256    # concatenated input feature width     [UNCHANGED]
ENC_GRU_HIDDEN        = 128    # GRU hidden state size                [UNCHANGED]
ENC_GRU_N_LAYERS      = 2      # stacked GRU depth                    [UNCHANGED]
ENC_TIME2VEC_K        = 8      # number of Time2Vec sine terms        [UNCHANGED]
ENC_PROJ_DIM           = 128    # projection head output dim           [UNCHANGED]
ENC_DROPOUT            = 0.1                                          # [UNCHANGED]

# -- Augmentation Pairs / Encoder Input (P1-M2, P1-M3)  [NEW SECTION] --
AUG_PAIRS_NUMERIC_COLS      = ['value_norm', 'hour_of_day', 'day_of_week']  # was 14 cols
AUG_PAIRS_NUM_NUMERIC       = 3        # was 14
AUG_PAIRS_CATEGORICAL_COLS  = ['cloud', 'entity_type', 'namespace', 'metric_name']  # was 3
AUG_VALUE_NORM_EPS          = 1e-6     # floors per-metric std to avoid divide-by-zero
# AUG_PAIRS_METRIC_COLS / AUG_PAIRS_MASK_COLS -- REMOVED (no fixed metric list;
#   metric_name is now a learned categorical embedding, not hardcoded wide columns)
# metric_name vocab size is data-dependent -- computed via compute_vocab_sizes()
#   (do not hardcode)

# -- Training (P1-M4) -------------------------------------------
TRAIN_TEMPERATURE    = 0.07   # NT-Xent temperature (tau)            [UNCHANGED]
TRAIN_LR              = 1e-4   # AdamW learning rate   [OPEN RECONCILIATION ITEM]
TRAIN_WEIGHT_DECAY    = 1e-4                                         # [UNCHANGED]
TRAIN_GRAD_CLIP_NORM  = 1.0                                          # [UNCHANGED]
TRAIN_BATCH_SIZE      = 256                                          # [UNCHANGED]

# -- FAISS (P1-M5, P2-M9) ----------------------------------------
FAISS_N_LIST          = 100    # IVF cluster count
FAISS_N_PROBE          = 20     # clusters searched per query
FAISS_TOP_K             = 10     # k nearest episodes returned

# -- Ingestion (P2-M1) --------------------------------------------
INGEST_BATCH_WIN_SEC  = 300    # 5-minute batch window
INGEST_POLL_MS         = 100    # Kafka poll timeout

# -- Entity Store / Redis (P2-M6) ----------------------------------
REDIS_HISTORY_LEN     = 30     # rolling history window
REDIS_EMB_BYTES        = 256    # 128 * float16
REDIS_DEDUP_TTL         = 300    # dedup window TTL (seconds)
REDIS_DRIFT_CACHE_TTL  = 1800   # MMD cache TTL (seconds)

# -- Detection Thresholds (P2-M7, P2-M8, P2-M10) --------------------
SCORE_W_DEVIATION      = 0.4    # weight in final anomaly formula
SCORE_W_DRIFT           = 0.4
SCORE_W_SIMILARITY      = 0.2
SCORE_GLOBAL_THRESH     = 0.3    # cosine deviation flag threshold
SCORE_LOCAL_THRESH      = 0.25
SCORE_DRIFT_THRESH      = 0.5
SCORE_SEV_MEDIUM        = 0.3    # severity cutoffs
SCORE_SEV_HIGH           = 0.6
SCORE_SEV_CRITICAL       = 0.8

# -- Reference encoder (P2-M4) --------------------------------------
REF_HISTORY_DAYS       = 90     # past window for MMD baseline
REF_CENTROID_ALPHA     = 0.1    # EMA update factor