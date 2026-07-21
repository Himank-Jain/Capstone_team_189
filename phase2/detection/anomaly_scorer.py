"""
phase2/detection/anomaly_scorer.py
=====================================================
P2-M10  Final Anomaly Score — AnomalyScorer
CAPSTONE-189

[P2-M10 AnomalyScorer] (primer, Project Directory Structure §6c)
Input: ScoringInput(entity_id, deviation_score, drift_score,
similarity_score, batch_ts). Formula:
final_score = SCORE_W_DEVIATION*deviation_score
             + SCORE_W_DRIFT*drift_score
             + SCORE_W_SIMILARITY*(1-similarity_score)
Severity from constants: <SCORE_SEV_MEDIUM -> LOW, <SCORE_SEV_HIGH -> MEDIUM,
<SCORE_SEV_CRITICAL -> HIGH, else CRITICAL. Missing drift_score (None) ->
SCORE_DRIFT_FALLBACK (0.5). Missing similarity_score (None, e.g. new
entity / empty FAISS index) -> SCORE_SIMILARITY_FALLBACK (0.0).

Import constraint
------------------
Same rule already established by P2-M7/P2-M8/P2-M9 (see their own module
docstrings): this module imports ONLY from shared/types.py and
shared/constants.py. It does not import CosineDeviationScorer,
MmdDriftMonitor, EpisodeRetriever, AsyncDriftWorker, or anything else
under phase2/ -- an orchestrator (a future scripts/run_inference.py or
the P2-M1..P2-M9 wiring) is responsible for calling those three modules
and reducing their outputs to the scalars ScoringInput expects. This
keeps AnomalyScorer trivially unit-testable with plain floats and
protects against the exact kind of tight coupling the Directory
Structure's DIP section warns about ("AnomalyScorer importing
CosineDeviationScorer at the top of the file and instantiating it
internally... untestable and tightly coupled").

Design note -- deviation from the Directory Structure's DIP sketch
---------------------------------------------------------------------
Section 4 (DIP) of the Directory Structure sketches an AnomalyScorer whose
constructor accepts BaseDeviationScorer / BaseDriftMonitor /
BaseEpisodeRetriever abstractions -- i.e. a version of this class that
orchestrates P2-M7/M8/M9 itself. The as-built P2-M7/M8/M9 modules don't
follow that shape, though: each is a pure function over data the CALLER
already fetched (CosineDeviationScorer takes CurrentEmbedding +
EntityProfile, not an EntityStoreReader; MmdDriftMonitor takes an
injected reader but performs no orchestration of the other two scores at
all). Matching that established, actually-built pattern -- and the P2-M10
ticket's own AI Prompt Brief, which is unambiguous ("Implement an
AnomalyScorer with the formula... (1) ScoringInput dataclass... (2)
AnomalyResult dataclass...") -- AnomalyScorer here is likewise a pure
function: score(ScoringInput) -> AnomalyResult, no I/O, no constructor
dependencies on the other detection modules. If a future module wants the
DIP-style orchestrating variant, it belongs one layer up (an
AnomalyScoringPipeline / IngestionPipeline-style Controller), not inside
AnomalyScorer itself -- consistent with Low Coupling.

Everything below is pure numpy-free arithmetic per the ticket's own Tech
Stack line ("NumPy") -- no numpy is actually needed for scalar math, so
none is imported; this keeps the module dependency-free beyond the
project's own shared/ package.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from shared.constants import (
    SCORE_DRIFT_FALLBACK,
    SCORE_SEV_CRITICAL,
    SCORE_SEV_HIGH,
    SCORE_SEV_MEDIUM,
    SCORE_SIMILARITY_FALLBACK,
    SCORE_W_DEVIATION,
    SCORE_W_DRIFT,
    SCORE_W_SIMILARITY,
)
from shared.types import (
    AnomalyResult,
    DeviationResult,
    DriftScore,
    EpisodeSearchResult,
    ScoringInput,
    Severity,
)

logger_obj: logging.Logger = logging.getLogger(__name__)


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


class SeverityMapper:
    """
    Maps a final_score in [0,1] to a Severity. Thresholds are constructor
    args defaulting to the shared/constants.py values (which are, in turn,
    loaded from config/config.yaml by ConfigLoader upstream) -- per the
    ticket: "configurable thresholds from YAML", never hardcoded inline.

    Boundaries are inclusive on the LOWER bound of each band, matching the
    Team Planner's own table verbatim:
        <0.3            -> LOW
        0.3 <= x < 0.6  -> MEDIUM
        0.6 <= x < 0.8  -> HIGH
        >=0.8           -> CRITICAL
    """

    def __init__(
        self,
        sev_medium_threshold: float = SCORE_SEV_MEDIUM,
        sev_high_threshold: float = SCORE_SEV_HIGH,
        sev_critical_threshold: float = SCORE_SEV_CRITICAL,
    ) -> None:
        if not (0.0 <= sev_medium_threshold < sev_high_threshold < sev_critical_threshold <= 1.0):
            raise ValueError(
                "[SeverityMapper] thresholds must satisfy "
                "0 <= sev_medium < sev_high < sev_critical <= 1, got "
                f"({sev_medium_threshold}, {sev_high_threshold}, {sev_critical_threshold})"
            )
        self._sev_medium = sev_medium_threshold
        self._sev_high = sev_high_threshold
        self._sev_critical = sev_critical_threshold

    def classify(self, final_score: float) -> Severity:
        if final_score >= self._sev_critical:
            return Severity.CRITICAL
        if final_score >= self._sev_high:
            return Severity.HIGH
        if final_score >= self._sev_medium:
            return Severity.MEDIUM
        return Severity.LOW


class AnomalyScorer:
    """
    Stateless -- holds only weights + a SeverityMapper, mirroring
    CosineDeviationScorer's "holds only threshold values" convention.

    Parameters
    ----------
    w_deviation, w_drift, w_similarity:
        Formula weights. Default to SCORE_W_DEVIATION/DRIFT/SIMILARITY
        (0.4/0.4/0.2) from shared/constants.py. Not required to sum to 1
        (not enforced) -- config.yaml is the source of truth if these are
        ever retuned, per the ticket's "document these as configurable
        constants... not hardcoded" instruction; this class simply
        accepts whatever it's given.
    severity_mapper:
        Injected SeverityMapper. Defaults to one built from the constants
        module if not supplied (DIP-lite: swappable for tests without a
        full ConfigLoader).
    """

    def __init__(
        self,
        w_deviation: float = SCORE_W_DEVIATION,
        w_drift: float = SCORE_W_DRIFT,
        w_similarity: float = SCORE_W_SIMILARITY,
        severity_mapper: Optional[SeverityMapper] = None,
    ) -> None:
        self._w_deviation = w_deviation
        self._w_drift = w_drift
        self._w_similarity = w_similarity
        self._severity_mapper = severity_mapper if severity_mapper is not None else SeverityMapper()

    def score(self, scoring_input: ScoringInput) -> AnomalyResult:
        """
        Apply the weighted formula and map to severity. Never raises for
        missing drift/similarity -- those get the documented fallbacks
        (see module docstring / shared/constants.py additions).
        """
        deviation_score = _clip01(scoring_input.deviation_score)

        if scoring_input.drift_score is None:
            logger_obj.debug(
                "[AnomalyScorer] entity_id=%s drift_score is None -- using "
                "SCORE_DRIFT_FALLBACK=%s", scoring_input.entity_id, SCORE_DRIFT_FALLBACK,
            )
            drift_score = SCORE_DRIFT_FALLBACK
        else:
            drift_score = _clip01(scoring_input.drift_score)

        if scoring_input.similarity_score is None:
            logger_obj.debug(
                "[AnomalyScorer] entity_id=%s similarity_score is None -- using "
                "SCORE_SIMILARITY_FALLBACK=%s", scoring_input.entity_id, SCORE_SIMILARITY_FALLBACK,
            )
            similarity_score = SCORE_SIMILARITY_FALLBACK
        else:
            similarity_score = _clip01(scoring_input.similarity_score)

        deviation_contribution = self._w_deviation * deviation_score
        drift_contribution = self._w_drift * drift_score
        similarity_contribution = self._w_similarity * (1.0 - similarity_score)

        final_score = _clip01(deviation_contribution + drift_contribution + similarity_contribution)
        severity = self._severity_mapper.classify(final_score)

        return AnomalyResult(
            entity_id=scoring_input.entity_id,
            final_score=final_score,
            severity=severity,
            deviation_contribution=deviation_contribution,
            drift_contribution=drift_contribution,
            similarity_contribution=similarity_contribution,
            batch_ts=scoring_input.batch_ts,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Convenience builder -- reduces the actual P2-M7/M8/M9 output objects to the
# flat ScoringInput contract. Lives here (not in the orchestrator) because the
# reduction rules are P2-M10-owned domain knowledge, explicitly documented in
# the Team Planner:
#   * deviation_score = max(global_score, local_score)          [P2-M7 §Integration]
#   * similarity_score = mean of retrieved episode similarities  [P2-M9 §Integration]
# This function still only imports shared/types.py types (DeviationResult,
# DriftScore, EpisodeSearchResult are all already part of the shared contract)
# -- it does NOT import CosineDeviationScorer/MmdDriftMonitor/EpisodeRetriever
# themselves, so the "only shared/" import constraint above still holds.
# ─────────────────────────────────────────────────────────────────────────────

def build_scoring_input(
    entity_id: str,
    deviation_result: DeviationResult,
    drift_score_obj: Optional[DriftScore],
    episode_matches: List[EpisodeSearchResult],
    batch_ts,
) -> ScoringInput:
    """
    Reduce P2-M7/P2-M8/P2-M9's actual output types into the scalar
    ScoringInput contract AnomalyScorer.score() expects.

    Parameters
    ----------
    deviation_result:
        P2-M7 CosineDeviationScorer.compute_scores() output. Always
        present -- P2-M7 runs synchronously on the hot path and never
        returns None (its own "no profile" case is a concrete
        DeviationResult with global_score=local_score=0.5, not None).
    drift_score_obj:
        P2-M8's cached DriftScore, e.g. from
        AsyncDriftWorker.get_cached_drift(entity_id) -- None means no
        cached score exists yet (see this module's docstring for how
        that differs from MmdDriftMonitor's own internal 0.5 fallback).
    episode_matches:
        P2-M9 EpisodeRetriever.search() output. Empty list (not None) is
        the "nothing found" signal from that module -- handled the same
        as None here.
    """
    deviation_score = max(deviation_result.global_score, deviation_result.local_score)

    drift_score = drift_score_obj.drift_score if drift_score_obj is not None else None

    if episode_matches:
        similarity_score = sum(m.similarity_score for m in episode_matches) / len(episode_matches)
    else:
        similarity_score = None

    component_scores = {
        "global_deviation": deviation_result.global_score,
        "local_deviation": deviation_result.local_score,
        "n_episodes_retrieved": float(len(episode_matches)),
    }
    if drift_score_obj is not None:
        component_scores["drift_flag"] = float(drift_score_obj.drift_flag)

    return ScoringInput(
        entity_id=entity_id,
        deviation_score=deviation_score,
        drift_score=drift_score,
        similarity_score=similarity_score,
        batch_ts=batch_ts,
        component_scores=component_scores,
    )
