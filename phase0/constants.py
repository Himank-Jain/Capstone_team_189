"""
phase0/constants.py
=======================
CAPSTONE-189 · Phase 0 — Adaptive Statistical Baseline.

Self-contained: does NOT import from shared/constants.py. Phase 0 is
independent of Phases 1-2 by design (see Phase 0 Directory Structure doc,
Section 6 — Explicit Non-Dependencies).
"""

# -- Bucketing -----------------------------------------------------------
PHASE0_BUCKET_GRANULARITY_HOURS: int = 1     # 1 = hourly buckets (24/day)
PHASE0_SPLIT_WEEKDAY_WEEKEND: bool = True    # 24 buckets -> 48 if True

# -- Rolling baseline ------------------------------------------------------
PHASE0_WINDOW_SIZE_DAYS: int = 30            # how many past readings per bucket to retain
PHASE0_ZSCORE_THRESHOLD: float = 3.0         # |z| > this -> flagged anomalous
PHASE0_ROBUST_Z_CONSTANT: float = 0.6745     # consistency correction for MAD-based robust z-score
PHASE0_MIN_SAMPLES_FOR_SCORING: int = 5      # below this, a bucket is too new to score reliably

# -- Redis key schema -------------------------------------------------------
PHASE0_REDIS_KEY_PREFIX: str = "phase0:baseline"

# -- Scoring method ----------------------------------------------------------
PHASE0_SCORING_METHOD_ZSCORE: str = "zscore"
PHASE0_SCORING_METHOD_ROBUST_ZSCORE: str = "robust_zscore"
