"""
phase2/detection/cosine_deviation_scorer.py
=====================================================
P2-M7  Cosine Distance — CosineDeviationScorer
CAPSTONE-189

[P2-M7 CosineDeviationScorer] (primer, Project Directory Structure §6a)
Inputs: CurrentEmbedding + EntityProfile from EntityStoreReader.
global_score = 1 - dot(current_emb, centroid_emb) (both L2-norm so
dot=cosine). local_score = mean(1 - current_emb @ history_embs.T)
(vectorised). global_flag = global_score > SCORE_GLOBAL_THRESH=0.3.
local_flag = local_score > SCORE_LOCAL_THRESH=0.25. Returns
DeviationResult.

Import constraint
------------------
Per the Directory Structure Addendum's LLM primer for this module: "Do
not import from phase2/ -- only from shared/types.py and
shared/constants.py." This class never touches Redis, EntityStoreReader,
or any other phase2 module. Fetching CurrentEmbedding/EntityProfile out
of the store is the CALLER's job (an inference-loop orchestrator, e.g.
scripts/run_inference.py) -- this keeps CosineDeviationScorer trivially
unit-testable with plain dataclasses and swappable if the store backend
ever changes (Redis -> PgVector), matching the "Protected Variations"
principle documented alongside BaseEntityStore.

Cold start
----------
EntityProfile.cold_start_flag is set upstream (P2-M4/ReferenceEncoderService
seeds a new entity's centroid_emb from the global mean rather than leaving
it absent) -- when a profile like that is passed in, this module scores it
exactly like any other profile; it does not re-derive cold-start logic.
The one case this module DOES special-case is `profile is None`, i.e. the
entity has no profile in the store at all yet (EntityStoreReader.fetch_
entity_profile returned None). DeviationResult's frozen field list (see
shared/types.py) has no cold_start slot, so that case is signalled the
same neutral way the original P2-M7 ticket specified before EntityProfile
existed: global_score=local_score=0.5, both flags False -- distinguishable
by the caller as "no profile" only via the None-profile branch itself
(e.g. checking EntityStoreReader.fetch_entity_profile(...) is None before
calling compute_scores), not via any field on the result.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np

from shared.constants import SCORE_GLOBAL_THRESH, SCORE_LOCAL_THRESH
from shared.types import CurrentEmbedding, DeviationResult, EntityProfile


def compute_cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """1 - dot(a,b)/(|a||b|). Both project vectors are L2-normalised by
    contract, so this reduces to 1 - dot(a,b) in practice -- kept as the
    general form for anything that can't guarantee normalization (e.g.
    a stray non-unit vector in a test)."""
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 1.0
    return float(np.clip(1.0 - float(np.dot(a, b)) / denom, 0.0, 1.0))


class CosineDeviationScorer:
    """Stateless -- holds only the two threshold values, no store, no config
    beyond what's passed per call (mirrors CurrentEmbeddingAggregator's
    "stateless" convention)."""

    def __init__(
        self,
        global_threshold: float = SCORE_GLOBAL_THRESH,
        local_threshold: float = SCORE_LOCAL_THRESH,
    ):
        self.global_threshold = global_threshold
        self.local_threshold = local_threshold

    def compute_scores(
        self,
        current_emb: CurrentEmbedding,
        profile: Optional[EntityProfile],
    ) -> DeviationResult:
        """
        Parameters
        ----------
        current_emb:
            P2-M5 output for this entity/batch.
        profile:
            EntityProfile fetched by the caller via EntityStoreReader.
            None means the entity has no profile in the store at all
            (brand new, never scored before) -- see module docstring.
        """
        emb = np.asarray(current_emb.emb, dtype=np.float32)

        if profile is None:
            return DeviationResult(
                entity_id=current_emb.entity_id,
                global_score=0.5,
                local_score=0.5,
                global_flag=False,
                local_flag=False,
                batch_ts=current_emb.batch_ts,
            )

        global_score = compute_cosine_distance(emb, profile.centroid_emb)

        if len(profile.history_embs) == 0:
            # No window history yet (very new entity) -- fall back to the
            # global score rather than fabricate a number or divide by zero.
            local_score = global_score
        else:
            local_score = self._compute_local_deviation(emb, profile.history_embs)

        return DeviationResult(
            entity_id=current_emb.entity_id,
            global_score=global_score,
            local_score=local_score,
            global_flag=global_score > self.global_threshold,
            local_flag=local_score > self.local_threshold,
            batch_ts=current_emb.batch_ts,
        )

    @staticmethod
    def _compute_local_deviation(current: np.ndarray, history_embs: List[np.ndarray]) -> float:
        # Stack variable-length history (<= REDIS_HISTORY_LEN) into (N, 128)
        # and do one matrix-vector multiply instead of N python-level calls.
        matrix = np.stack([np.asarray(h, dtype=np.float32) for h in history_embs])
        dots = matrix @ current
        distances = np.clip(1.0 - dots, 0.0, 1.0)
        return float(np.mean(distances))
