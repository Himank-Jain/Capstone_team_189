"""
shared/types.py -- ADDITIONS for P2-M10 (AnomalyScorer)
=========================================================
CAPSTONE-189

PATCH, not a full file. Append below. Corrected against the actual
current shared/types.py (uploaded): that file only defines RawRecord,
EventBatch, EntityProfile, CurrentEmbedding, DeviationResult, DriftScore
so far. DeviationResult and DriftScore already match what
anomaly_scorer.py / build_scoring_input() expect field-for-field --
NOT redefined here. Everything below is new:

  * Severity            -- did NOT already exist (an earlier pass assumed
                            it did, from the pre-Addendum Directory
                            Structure sketch -- it was never actually
                            added to this file). AnomalyResult.severity
                            needs it.
  * EpisodeSearchResult  -- technically P2-M9's output type, not P2-M10's.
                            Added here because build_scoring_input()
                            (anomaly_scorer.py) takes
                            List[EpisodeSearchResult] as an argument and
                            needs the type to exist to import cleanly.
                            Field shape matches episode_retriever.py's
                            actual EpisodeSearchResult construction
                            exactly (similarity_score, episode_id,
                            entity_id, timestamp, cloud_provider,
                            severity_label). If/when P2-M9 is merged
                            through its own PR, treat that PR as
                            canonical for this dataclass and drop it from
                            here rather than maintaining two copies.
  * ScoringInput         -- P2-M10's own input contract.
  * AnomalyResult        -- P2-M10's own output contract.

Add `from enum import Enum` to this file's existing import block if it
isn't already there (the current uploaded file doesn't import it).
"""

from dataclasses import dataclass, field   # already imported in the real file -- shown for a standalone-readable patch
from datetime import datetime
from enum import Enum                      # NOT already imported in the real file -- add this line
from typing import Dict, Optional


# ── New: did not previously exist in shared/types.py ───────────────────────

class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class EpisodeSearchResult:
    """
    One historical episode match returned by EpisodeRetriever.search()
    (P2-M9). Added here (rather than only in a future P2-M9 PR) because
    AnomalyScorer's build_scoring_input() helper (P2-M10) needs the type
    to exist. See this file's patch-level docstring above for the
    "who owns this" note.

    Parameters
    ----------
    similarity_score:
        Cosine similarity in [0,1] to the query embedding (converted from
        FAISS's squared-L2 distance -- see episode_retriever.py).
    episode_id:
        Synthesized from the FAISS internal vector index position
        (stable -- vectors are only ever appended, never reordered).
    entity_id:
        Entity the matched historical episode belongs to.
    timestamp:
        UTC datetime of the matched episode, if the FAISS metadata row
        carried one.
    cloud_provider:
        AWS | Azure | GCP | OCI | Unknown.
    severity_label:
        Historical severity label if one was tagged at index-build time
        (commonly None in the real corpus -- see episode_retriever.py).
    """
    similarity_score: float
    episode_id: str
    entity_id: str
    timestamp: Optional[datetime]
    cloud_provider: str
    severity_label: Optional[str]


@dataclass
class ScoringInput:
    """
    Input contract for AnomalyScorer.score() (P2-M10). Holds resolved
    SCALARS, not the upstream DeviationResult/DriftScore/
    List[EpisodeSearchResult] objects themselves -- see
    anomaly_scorer.py's module docstring for why (matches the pure-
    function pattern P2-M7/M8/M9 already established, and the P2-M10
    ticket's own AI Prompt Brief verbatim).

    Parameters
    ----------
    entity_id:
        Unique identifier for the monitored resource.
    deviation_score:
        [0,1]. Always available -- P2-M7 runs synchronously and never
        returns a missing result (its own "no profile" case is a
        concrete DeviationResult with global_score=local_score=0.5, not
        an absence).
    drift_score:
        [0,1] or None. None means no cached DriftScore exists yet for
        this entity (e.g. AsyncDriftWorker.get_cached_drift() returned
        None) -- AnomalyScorer substitutes SCORE_DRIFT_FALLBACK.
    similarity_score:
        [0,1] or None. None means no episode matches came back (new
        entity, or an empty/cold FAISS index) -- AnomalyScorer
        substitutes SCORE_SIMILARITY_FALLBACK.
    batch_ts:
        UTC timestamp this scoring pass corresponds to.
    component_scores:
        Optional pass-through breakdown for explainability/logging only
        (e.g. {'global_deviation': .., 'local_deviation': ..,
        'n_episodes_retrieved': ..}). Not read by AnomalyScorer.score()
        itself -- carried through for a future P2-M14 alert payload.
    """
    entity_id: str
    deviation_score: float
    drift_score: Optional[float]
    similarity_score: Optional[float]
    batch_ts: datetime
    component_scores: Dict[str, float] = field(default_factory=dict)


@dataclass
class AnomalyResult:
    """
    Output of AnomalyScorer.score() (P2-M10). Consumed downstream by
    AlertDeduplicator (P2-M11).

    Parameters
    ----------
    entity_id:
        Unique identifier for the monitored resource.
    final_score:
        [0,1]. SCORE_W_DEVIATION*deviation + SCORE_W_DRIFT*drift +
        SCORE_W_SIMILARITY*(1-similarity), with fallbacks applied.
    severity:
        Severity enum, from SeverityMapper.classify(final_score).
    deviation_contribution / drift_contribution / similarity_contribution:
        The three weighted terms that sum to final_score -- carried
        individually for explainability (P2-M14's alert payload).
    batch_ts:
        UTC timestamp carried through from the originating ScoringInput.
    """
    entity_id: str
    final_score: float
    severity: Severity
    deviation_contribution: float
    drift_contribution: float
    similarity_contribution: float
    batch_ts: datetime
