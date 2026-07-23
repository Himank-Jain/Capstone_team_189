"""
"""

INGEST_BATCH_WIN_SEC: int = 300
INGEST_POLL_MS: int = 100

AUG_CATEGORICAL_COLS: list[str] = ["cloud", "entity_type", "namespace", "metric_name"]
AUG_PAIRS_CATEGORICAL_COLS = AUG_CATEGORICAL_COLS
AUG_TIME_SCALAR_COLS: list[str] = ["hour_of_day", "day_of_week"]
AUG_NUMERIC_COLS: list[str] = ["value_norm", *AUG_TIME_SCALAR_COLS]
AUG_PAIRS_NUM_NUMERIC: int = 3
AUG_VALUE_NORM_EPS: float = 1e-6

ENC_EMBED_DIM: int = 128
ENC_FEATURE_DIM: int = 256
REF_HISTORY_DAYS: int = 90
REF_HISTORY_LEN: int = 30
REF_CENTROID_ALPHA: float = 0.1
REF_DRIFT_ALARM_STD: float = 3.0
REF_SEQ_LEN: int = 32
REDIS_HISTORY_LEN: int = 30
REDIS_EMB_BYTES: int = 128 * 2
REDIS_DRIFT_CACHE_TTL: int = 1800
SCORE_GLOBAL_THRESH: float = 0.3
SCORE_LOCAL_THRESH: float = 0.25
SCORE_DRIFT_THRESH: float = 0.5
FAISS_TOP_K: int = 10
FAISS_N_LIST: int = 100
FAISS_N_PROBE: int = 20
EPISODE_CACHE_TTL_SEC: int = 1800
MMD_DEFAULT_SIGMA: float = 1.0
MMD_MAX_SAMPLES_PER_DIST: int = 200
MMD_RECENT_FRACTION: float = 1.0 / 3.0
MMD_MIN_SAMPLES_PER_DIST: int = 5
MMD_NULL_CALIBRATION_PAIRS: int = 1000
MMD_NULL_CALIBRATION_PERCENTILE: float = 99.0
"""shared/constants.py -- COMBINED ADDITIONS for P2-M11, P2-M12, P2-M10
=======================================================================
CAPSTONE-189

PATCH BUNDLE, not a full file. This concatenates three append-only
patches, in the order they were produced, so they can be reviewed and
applied to the real shared/constants.py as one pass instead of three
separate diffs. Each section below is otherwise UNCHANGED from its
original patch -- nothing was re-derived or altered when combining.

  Section 1 -- P2-M11 (AlertDeduplicator)   -- DEDUP_*
  Section 2 -- P2-M12 (CorrelationEngine)   -- CORR_*
  Section 3 -- P2-M10 (AnomalyScorer)       -- SCORE_*

Apply in this order if applying incrementally, since each section's own
docstring context (e.g. P2-M10's note about what already existed at the
time it was written) assumes the prior sections are already present.
"""

# =========================================================================
# Section 1 -- Alert Deduplication (P2-M11)
# =========================================================================
# Single source for BOTH the window bucket AND Redis TTL -- deliberately,
# per the planner's own "TTL must match window exactly" warning.
DEDUP_WINDOW_SEC: int = 300              # 5-minute dedup window
DEDUP_FEATURE_BUCKET_SIZE: float = 0.1   # rounding granularity for AnomalyResult's
                                          # contribution scores before fingerprinting
                                          # (practical stand-in for a true similarity
                                          # metric -- see alert_deduplicator.py docstring)

# =========================================================================
# Section 2 -- Alert Correlation (P2-M12)
# =========================================================================
CORR_EDGE_TIME_WINDOW_SEC: int = 600        # "both alerted in the last 10 minutes"
                                             # edge condition (Team Planner P2-M12,
                                             # CorrelationEngine primer)
CORR_PRUNE_INACTIVE_SEC: int = 1800         # remove nodes with no alert in last 30 min
                                             # (planner's "What to Watch Out For" + primer)
CORR_MIN_SHARED_ATTRS: int = 2              # >=2 shared attrs among
                                             # (cloud_provider, region, op_id) required
                                             # for an edge (Directory Structure primer:
                                             # "Edges: >=2 shared attrs + both alerted
                                             # in last 10 min")
CORR_REGIONAL_GROUP_SIZE_THRESHOLD: int = 10  # group_size > 10 (i.e. 11+) is the
                                               # REGIONAL_OUTAGE candidate size
CORR_LOUVAIN_RANDOM_STATE: int = 42         # seed for reproducible Louvain community
                                             # detection (planner: "Louvain is
                                             # non-deterministic -- set random_state
                                             # for reproducibility in tests")

# =========================================================================
# Section 3 -- Final Anomaly Score (P2-M10)
# =========================================================================
# Formula: final = SCORE_W_DEVIATION*deviation_score
#                 + SCORE_W_DRIFT*drift_score
#                 + SCORE_W_SIMILARITY*(1 - similarity_score)
#
# Verified against the previously-uploaded shared/constants.py:
# SCORE_GLOBAL_THRESH, SCORE_LOCAL_THRESH (P2-M7) and SCORE_DRIFT_THRESH
# (P2-M8) already exist there -- NOT redefined here. The six weight/
# severity/fallback constants below did not exist anywhere -- all new.
SCORE_W_DEVIATION: float = 0.4
SCORE_W_DRIFT: float = 0.4
SCORE_W_SIMILARITY: float = 0.2

# Severity mapping on final_score, all lower-bound-inclusive:
#   <SCORE_SEV_MEDIUM                     -> LOW
#   SCORE_SEV_MEDIUM..<SCORE_SEV_HIGH     -> MEDIUM
#   SCORE_SEV_HIGH..<SCORE_SEV_CRITICAL   -> HIGH
#   >=SCORE_SEV_CRITICAL                  -> CRITICAL
SCORE_SEV_MEDIUM: float = 0.3
SCORE_SEV_HIGH: float = 0.6
SCORE_SEV_CRITICAL: float = 0.8

# Fallbacks for ScoringInput.drift_score / .similarity_score == None
# (see shared/types.py ScoringInput docstring for exactly when each
# None case arises).
SCORE_DRIFT_FALLBACK: float = 0.5        # matches MmdDriftMonitor's own neutral fallback
SCORE_SIMILARITY_FALLBACK: float = 0.0   # worst-case: no similarity data -> full penalty
