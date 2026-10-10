"""
phase2/detection/mmd_drift_monitor.py
=====================================================
P2-M8  MMD Drift Monitor — mmd_rbf / MmdDriftMonitor
CAPSTONE-189

[P2-M8 MmdDriftMonitor] (primer, Project Directory Structure §6c)
MMD^2 with RBF kernel. Sigma via median heuristic. Subsample to 200 per
distribution. Compares REF_HISTORY_DAYS=90d vs recent 30d embs from
EntityStoreReader. Scaled via per-entity empirical 99th-percentile null
calibration. Returns DriftScore.

Import constraint
------------------
Same rule as P2-M7 (see cosine_deviation_scorer.py's module docstring):
this module depends on `phase2.store.base_entity_store.BaseEntityStoreReader`
for its input type ONLY -- it takes a reader instance injected by the
caller (e.g. AsyncDriftWorker, or scripts/run_p2m8_against_entity_store.py)
rather than constructing one itself, so it stays swappable and testable
with a fake reader.

Where "past 90 days vs recent 30 days" actually comes from
------------------------------------------------------------
The ticket's data-source description doesn't match what P2-M6 actually
persists. `EntityProfile.history_embs` (base_entity_store.py, frozen /
"Unchanged" per the Directory Structure Addendum) is capped at
REDIS_HISTORY_LEN=30 window-embeddings TOTAL -- there is no separate
90-day raw embedding store anywhere in the as-built system, and
`centroid_emb` is an EMA scalar-pooled summary (a single point), not a
sample-able distribution. Two options were on the table:

  1. Fabricate a second store P2-M8 alone depends on (a 90-day raw
     embedding log) that no other module writes to or agrees on. This
     would violate the "shared/types.py is the single source of truth"
     rule the project already established (see shared/types.py's module
     docstring) and silently diverge from what P2-M6 actually offers.
  2. Treat the REAL data P2-M6 gives every other detection module --
     `history_embs`, chronological oldest-first -- as the population to
     split, using MMD_RECENT_FRACTION (shared/constants.py) to carve off
     a NEWER "recent" slice vs an OLDER "past" slice, standing in for the
     30-of-120-day ratio the ticket describes.

Option 2 is what this module does. It is a real distribution-vs-
distribution MMD comparison over genuine per-entity behavioral history
(not a mock), it needs zero new store surface, and it degrades honestly:
an entity with too little history to trust a split (see
MMD_MIN_SAMPLES_PER_DIST) gets the documented neutral fallback instead of
a fabricated number.

What to watch out for (from the ticket, followed here)
---------------------------------------------------------
* MMD is O(N^2) -- subsample each side to MMD_MAX_SAMPLES_PER_DIST=200
  (see `_subsample`). With history capped at 30, this cap essentially
  never bites today, but is real and tested for whenever REDIS_HISTORY_LEN
  is raised later.
* Sigma (RBF bandwidth) is calibrated via the median heuristic:
  sigma = median(pairwise distances) / sqrt(2), with a degenerate-median
  fallback to MMD_DEFAULT_SIGMA.
* This module performs NO I/O and NO threading itself -- it is pure
  numpy/scipy math over arrays the caller already fetched. Running it off
  the hot inference path is AsyncDriftWorker's job (async_drift_worker.py),
  exactly like CosineDeviationScorer never touches Redis itself.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.spatial.distance import pdist

from phase2.store.base_entity_store import BaseEntityStoreReader
from shared.constants import (
    MMD_DEFAULT_SIGMA,
    MMD_MAX_SAMPLES_PER_DIST,
    MMD_MIN_SAMPLES_PER_DIST,
    MMD_NULL_CALIBRATION_PAIRS,
    MMD_NULL_CALIBRATION_PERCENTILE,
    MMD_RECENT_FRACTION,
    SCORE_DRIFT_THRESH,
)
from shared.types import DriftScore

logger_obj: logging.Logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pure MMD math -- no store, no I/O
# ─────────────────────────────────────────────────────────────────────────────

def rbf_kernel_matrix(A: np.ndarray, B: np.ndarray, sigma: float) -> np.ndarray:
    """k(a,b) = exp(-||a-b||^2 / (2*sigma^2)) for every pair (a in A, b in B).

    Vectorised via the standard ||a-b||^2 = |a|^2 + |b|^2 - 2*a.b expansion
    so this is one matmul + broadcasting, not a python-level double loop --
    this is the "efficient O(N^2) estimator using matrix operations" the
    ticket asks for (O(N^2) in pair count is unavoidable for MMD itself;
    the efficiency win is doing all pairs in one vectorised shot instead of
    N*M scalar kernel calls).
    """
    if sigma <= 0:
        raise ValueError(f"[mmd_drift_monitor] sigma must be > 0, got {sigma}")
    A = np.asarray(A, dtype=np.float64)
    B = np.asarray(B, dtype=np.float64)
    sq_a = np.sum(A * A, axis=1)[:, None]        # (N,1)
    sq_b = np.sum(B * B, axis=1)[None, :]        # (1,M)
    sq_dists = sq_a + sq_b - 2.0 * (A @ B.T)      # (N,M)
    sq_dists = np.clip(sq_dists, 0.0, None)       # guard against tiny negative fp noise
    return np.exp(-sq_dists / (2.0 * sigma * sigma))


def mmd_rbf(X: np.ndarray, Y: np.ndarray, sigma: float = 1.0) -> float:
    """
    Unbiased MMD^2 estimator with an RBF kernel:

        MMD^2 = E[k(x,x')] + E[k(y,y')] - 2*E[k(x,y)]

    where the two within-sample expectations exclude the diagonal (x != x',
    y != y') -- the standard unbiased U-statistic estimator. Requires
    N = len(X) >= 2 and M = len(Y) >= 2 (an unbiased within-sample term is
    undefined for a single point). The result can be slightly negative due
    to estimator variance on small samples; callers that need a
    non-negative "distance-like" quantity should clip at 0 themselves
    (MmdDriftMonitor does this at the point it scales the score, not here,
    so this function stays a faithful implementation of the estimator).

    Parameters
    ----------
    X: ndarray (N, D)
    Y: ndarray (M, D)
    sigma: RBF bandwidth (> 0).
    """
    X = np.asarray(X, dtype=np.float64)
    Y = np.asarray(Y, dtype=np.float64)
    if X.ndim != 2 or Y.ndim != 2:
        raise ValueError(
            f"[mmd_drift_monitor] X, Y must be 2-D (N,D) arrays, got shapes "
            f"{X.shape}, {Y.shape}"
        )
    n, m = X.shape[0], Y.shape[0]
    if n < 2 or m < 2:
        raise ValueError(
            f"[mmd_drift_monitor] mmd_rbf needs >=2 samples per side for the "
            f"unbiased estimator, got n={n}, m={m}"
        )

    Kxx = rbf_kernel_matrix(X, X, sigma)
    Kyy = rbf_kernel_matrix(Y, Y, sigma)
    Kxy = rbf_kernel_matrix(X, Y, sigma)

    # Exclude diagonal terms (x_i vs itself) from the within-sample means --
    # that is what makes this the *unbiased* estimator rather than the
    # (biased, diagonal-inclusive) plug-in one.
    sum_xx = (Kxx.sum() - np.trace(Kxx)) / (n * (n - 1))
    sum_yy = (Kyy.sum() - np.trace(Kyy)) / (m * (m - 1))
    sum_xy = Kxy.mean()

    return float(sum_xx + sum_yy - 2.0 * sum_xy)


def median_heuristic_sigma(X: np.ndarray, Y: np.ndarray, default_sigma: float = MMD_DEFAULT_SIGMA) -> float:
    """
    sigma = median(pairwise distances of the POOLED X+Y sample) / sqrt(2).

    Falls back to `default_sigma` when the pooled sample has fewer than 2
    points, or when the median pairwise distance is (numerically) zero --
    e.g. every embedding in the pool is identical, which would otherwise
    produce sigma=0 and a divide-by-zero in the RBF kernel.
    """
    pooled = np.concatenate([np.asarray(X, dtype=np.float64), np.asarray(Y, dtype=np.float64)], axis=0)
    if pooled.shape[0] < 2:
        return default_sigma
    pairwise = pdist(pooled, metric="euclidean")
    if pairwise.size == 0:
        return default_sigma
    med = float(np.median(pairwise))
    if med <= 1e-12:
        logger_obj.warning(
            "[mmd_drift_monitor] median heuristic degenerated (median pairwise "
            "distance ~= 0, pool size=%d) -- falling back to default sigma=%.3f",
            pooled.shape[0], default_sigma,
        )
        return default_sigma
    return med / np.sqrt(2.0)


# ─────────────────────────────────────────────────────────────────────────────
# MmdDriftMonitor
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _NullCalibration:
    """Cached per-entity calibration: the scale denominator plus the sigma
    it was computed with, so a stale calibration (computed under a
    different sigma) is never silently reused."""
    scale_99th: float
    sigma: float


class MmdDriftMonitor:
    """
    Parameters
    ----------
    entity_store_reader:
        Anything satisfying BaseEntityStoreReader (P2-M6) -- fetches
        EntityProfile.history_embs for the entity being scored.
    max_samples_per_dist:
        Subsample cap per distribution (ticket: "Subsample to 200 max").
    recent_fraction:
        Fraction of history_embs (chronological oldest-first) treated as
        the "recent" distribution; the remainder is "past". See this
        module's docstring for why history_embs (not a literal 90-day
        store) is the split population.
    min_samples_per_dist:
        Minimum samples required on EACH side after the split (before
        subsampling) to trust an MMD estimate at all.
    null_calibration_pairs / null_calibration_percentile:
        Bootstrap-pair count and percentile used to build each entity's
        empirical null-distribution scale (see `_calibrate_null_scale`).
    rng:
        np.random.Generator used for subsampling and null-pair bootstrap
        draws. Inject a seeded generator in tests for determinism.
    """

    def __init__(
        self,
        entity_store_reader: BaseEntityStoreReader,
        max_samples_per_dist: int = MMD_MAX_SAMPLES_PER_DIST,
        recent_fraction: float = MMD_RECENT_FRACTION,
        min_samples_per_dist: int = MMD_MIN_SAMPLES_PER_DIST,
        null_calibration_pairs: int = MMD_NULL_CALIBRATION_PAIRS,
        null_calibration_percentile: float = MMD_NULL_CALIBRATION_PERCENTILE,
        drift_threshold: float = SCORE_DRIFT_THRESH,
        rng: Optional[np.random.Generator] = None,
    ) -> None:
        if not (0.0 < recent_fraction < 1.0):
            raise ValueError(
                f"[MmdDriftMonitor] recent_fraction must be in (0,1), got {recent_fraction}"
            )
        self._reader = entity_store_reader
        self._max_samples_per_dist = max_samples_per_dist
        self._recent_fraction = recent_fraction
        self._min_samples_per_dist = min_samples_per_dist
        self._null_calibration_pairs = null_calibration_pairs
        self._null_calibration_percentile = null_calibration_percentile
        self._drift_threshold = drift_threshold
        self._rng = rng if rng is not None else np.random.default_rng()

        # "on first run, compute ... to calibrate the 0-1 scaling" -- cached
        # per entity so repeated compute_drift() calls for the same entity
        # don't re-run a 1000-pair bootstrap every time. Guarded by a lock
        # since AsyncDriftWorker calls this from a ThreadPoolExecutor.
        self._null_cache: Dict[str, _NullCalibration] = {}
        self._null_cache_lock = threading.Lock()

    # ── Public API ──────────────────────────────────────────────────────────

    def compute_drift(self, entity_id: str) -> DriftScore:
        """
        Fetch entity_id's profile, split its history into past/recent,
        compute MMD^2, scale it via per-entity null calibration, and
        return a DriftScore. Never raises for "not enough data" cases --
        those get the documented neutral fallback instead (see
        `_neutral_fallback`).
        """
        profile = self._reader.fetch_entity_profile(entity_id)
        if profile is None:
            logger_obj.info(
                "[MmdDriftMonitor] entity_id=%s has no profile yet -- neutral fallback", entity_id
            )
            return self._neutral_fallback(entity_id)

        past, recent = self._split_history(profile.history_embs)
        if len(past) < self._min_samples_per_dist or len(recent) < self._min_samples_per_dist:
            logger_obj.info(
                "[MmdDriftMonitor] entity_id=%s insufficient history for a trustworthy "
                "MMD estimate (past=%d, recent=%d, need >=%d each) -- neutral fallback",
                entity_id, len(past), len(recent), self._min_samples_per_dist,
            )
            return self._neutral_fallback(entity_id)

        past_sub = self._subsample(past)
        recent_sub = self._subsample(recent)

        sigma = median_heuristic_sigma(past_sub, recent_sub)
        raw_mmd2 = mmd_rbf(past_sub, recent_sub, sigma=sigma)

        scale_99th = self._get_or_calibrate_null_scale(
            entity_id, past_sub, recent_sub, sigma
        )
        drift_score = self._scale_to_unit_interval(raw_mmd2, scale_99th)
        drift_flag = drift_score > self._drift_threshold

        return DriftScore(
            entity_id=entity_id,
            drift_score=drift_score,
            drift_flag=drift_flag,
            computed_at=datetime.now(timezone.utc),
        )

    def invalidate_calibration(self, entity_id: Optional[str] = None) -> None:
        """Drop cached null-scale calibration for one entity, or all
        entities if entity_id is None. Exposed for tests / long-running
        workers that want to force a fresh calibration periodically."""
        with self._null_cache_lock:
            if entity_id is None:
                self._null_cache.clear()
            else:
                self._null_cache.pop(entity_id, None)

    # ── Internals ───────────────────────────────────────────────────────────

    def _neutral_fallback(self, entity_id: str) -> DriftScore:
        """
        0.5 -- NOT 0.0 -- matching the project-wide "0.5 = no signal /
        unknown" convention already established by CosineDeviationScorer's
        no-profile case (shared/types.py DeviationResult) and by
        AnomalyScorer's documented stale-drift fallback (Directory
        Structure Addendum, P2-M10: "Missing drift -> use is_stale
        fallback=0.5"). Since SCORE_DRIFT_THRESH=0.5 and the flag condition
        is strictly `>`, 0.5 never trips drift_flag on its own.
        """
        return DriftScore(
            entity_id=entity_id,
            drift_score=0.5,
            drift_flag=False,
            computed_at=datetime.now(timezone.utc),
        )

    def _split_history(self, history_embs: List[np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
        """history_embs is chronological oldest-first (EntityProfile
        contract, shared/types.py). Split into an OLDER "past" prefix and
        a NEWER "recent" suffix using self._recent_fraction."""
        n = len(history_embs)
        recent_count = max(1, round(n * self._recent_fraction))
        recent_count = min(recent_count, n - 1) if n > 1 else recent_count
        past_count = n - recent_count
        stacked = np.stack([np.asarray(h, dtype=np.float64) for h in history_embs]) if n > 0 else np.zeros((0, 128))
        past = stacked[:past_count]
        recent = stacked[past_count:]
        return past, recent

    def _subsample(self, X: np.ndarray) -> np.ndarray:
        """Cap a distribution's sample count at self._max_samples_per_dist,
        subsampling WITHOUT replacement (ticket: "Subsample to 200 max")."""
        if X.shape[0] <= self._max_samples_per_dist:
            return X
        idx = self._rng.choice(X.shape[0], size=self._max_samples_per_dist, replace=False)
        return X[idx]

    def _get_or_calibrate_null_scale(
        self, entity_id: str, X: np.ndarray, Y: np.ndarray, sigma: float
    ) -> float:
        with self._null_cache_lock:
            cached = self._null_cache.get(entity_id)
            if cached is not None and cached.sigma == sigma:
                return cached.scale_99th

        scale_99th = self._calibrate_null_scale(X, Y, sigma)

        with self._null_cache_lock:
            self._null_cache[entity_id] = _NullCalibration(scale_99th=scale_99th, sigma=sigma)
        return scale_99th

    def _calibrate_null_scale(self, X: np.ndarray, Y: np.ndarray, sigma: float) -> float:
        """
        Null-distribution calibration (ticket item 4): "on first run,
        compute MMD on 1000 random same-distribution pairs to calibrate
        the 0-1 scaling."

        Implementation: pool X and Y (they're both this entity's own
        embeddings, just from different time slices, so under the null
        hypothesis "no real drift" they ARE the same distribution), then
        repeatedly bootstrap-resample (with replacement, since sample
        sizes here can be smaller than a clean permutation test wants) two
        same-size groups from the pool and compute MMD^2 between them.
        The MMD_NULL_CALIBRATION_PERCENTILE-th percentile of that null
        distribution becomes the denominator that maps a real MMD^2 onto
        [0,1]: a drift_score of 1.0 means "as extreme as the most extreme
        1% of pure-noise splits of this entity's own recent history."
        """
        pooled = np.concatenate([X, Y], axis=0)
        n_x, n_y = X.shape[0], Y.shape[0]
        pool_size = pooled.shape[0]

        null_values = np.empty(self._null_calibration_pairs, dtype=np.float64)
        for i in range(self._null_calibration_pairs):
            idx = self._rng.integers(0, pool_size, size=n_x + n_y)
            resampled = pooled[idx]
            null_x, null_y = resampled[:n_x], resampled[n_x:]
            null_values[i] = mmd_rbf(null_x, null_y, sigma=sigma)

        scale = float(np.percentile(null_values, self._null_calibration_percentile))
        # A degenerate (all-identical or near-zero-variance) pool can yield
        # scale <= 0; guard the caller's division against that.
        return scale if scale > 1e-12 else 1e-12

    @staticmethod
    def _scale_to_unit_interval(raw_mmd2: float, scale_99th: float) -> float:
        # raw_mmd2 can be slightly negative (unbiased estimator variance on
        # small samples, see mmd_rbf's docstring) -- clip at 0 before
        # scaling so "no drift" never reports as a negative score.
        clipped = max(raw_mmd2, 0.0)
        return float(np.clip(clipped / scale_99th, 0.0, 1.0))
