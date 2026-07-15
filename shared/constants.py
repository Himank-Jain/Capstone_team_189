"""
shared/constants.py  --  complete constant registry
=======================================================
CAPSTONE-189

Single source of truth for ALL UPPER_SNAKE + ModulePrefix constants used
across phase1/ and phase2/.
"""

# -- Encoder (P1-M3, P2-M3, P2-M4) -----------------------------
ENC_EMBED_DIM        = 128
ENC_FEATURE_DIM      = 256
ENC_GRU_HIDDEN       = 128
ENC_GRU_N_LAYERS     = 2
ENC_TIME2VEC_K       = 8
ENC_PROJ_DIM         = 128
ENC_DROPOUT          = 0.1

# -- Augmentation Pairs / Encoder Input (P1-M2, P1-M3) --
AUG_PAIRS_NUMERIC_COLS      = ['value_norm', 'hour_of_day', 'day_of_week']
AUG_PAIRS_NUM_NUMERIC       = 3
AUG_PAIRS_CATEGORICAL_COLS  = ['cloud', 'entity_type', 'namespace', 'metric_name']
AUG_VALUE_NORM_EPS          = 1e-6

# -- Training (P1-M4) -------------------------------------------
TRAIN_TEMPERATURE    = 0.07
TRAIN_LR             = 1e-4
TRAIN_WEIGHT_DECAY   = 1e-4
TRAIN_GRAD_CLIP_NORM = 1.0
TRAIN_BATCH_SIZE     = 256

# -- FAISS (P1-M5, P2-M9) ----------------------------------------
FAISS_N_LIST          = 100
FAISS_N_PROBE         = 20
FAISS_TOP_K           = 10
EPISODE_CACHE_TTL_SEC = 1800

# -- Ingestion (P2-M1) --------------------------------------------
INGEST_BATCH_WIN_SEC = 300
INGEST_POLL_MS       = 100

# -- Entity Store / Redis (P2-M6) ----------------------------------
REDIS_HISTORY_LEN     = 30
REDIS_EMB_BYTES       = 256
REDIS_DEDUP_TTL       = 300
REDIS_DRIFT_CACHE_TTL = 1800

# -- Detection Thresholds (P2-M7, P2-M8, P2-M10) --------------------
SCORE_W_DEVIATION    = 0.4
SCORE_W_DRIFT        = 0.4
SCORE_W_SIMILARITY   = 0.2
SCORE_GLOBAL_THRESH  = 0.3
SCORE_LOCAL_THRESH   = 0.25
SCORE_DRIFT_THRESH   = 0.5
SCORE_SEV_MEDIUM     = 0.3
SCORE_SEV_HIGH       = 0.6
SCORE_SEV_CRITICAL   = 0.8

# -- Reference encoder (P2-M4) --------------------------------------
REF_HISTORY_DAYS    = 90
REF_CENTROID_ALPHA  = 0.1
REF_HISTORY_LEN     = 30
REF_DRIFT_ALARM_STD = 3.0
REF_SEQ_LEN         = 32
