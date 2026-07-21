"""
shared/constants.py -- ADDITIONS for P2-M10 (AnomalyScorer)
==============================================================
CAPSTONE-189

PATCH, not a full file. Append as a new block. Corrected against the
actual current shared/constants.py (uploaded): that file's own scope note
says "SCORE_W_*, SCORE_SEV_* are documented in the same Addendum block
but belong to P2-M10 -- add them alongside that module, not here" --
meaning NONE of the six weight/severity constants exist yet, despite the
Directory Structure planning doc listing them as already registered. This
patch is the "alongside P2-M10" addition that note is deferring to.

Verified against the uploaded file: SCORE_GLOBAL_THRESH, SCORE_LOCAL_THRESH
(P2-M7) and SCORE_DRIFT_THRESH (P2-M8) already exist -- NOT redefined here.
SCORE_W_DEVIATION / SCORE_W_DRIFT / SCORE_W_SIMILARITY / SCORE_SEV_MEDIUM /
SCORE_SEV_HIGH / SCORE_SEV_CRITICAL / SCORE_DRIFT_FALLBACK /
SCORE_SIMILARITY_FALLBACK do NOT exist anywhere in the uploaded file --
all eight are new in this patch.

SCORE_DRIFT_FALLBACK is deliberately the SAME value (0.5) as
MmdDriftMonitor._neutral_fallback() uses for its own "insufficient data"
case -- both mean "not enough information to say anything about drift",
just reached via different paths (P2-M8's own fallback vs. P2-M10 finding
no cached DriftScore at all yet).
"""

# -- Final Anomaly Score (P2-M10) ----------------------------------------
# Formula: final = SCORE_W_DEVIATION*deviation_score
#                 + SCORE_W_DRIFT*drift_score
#                 + SCORE_W_SIMILARITY*(1 - similarity_score)
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
