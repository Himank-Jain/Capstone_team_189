"""
shared/types.py -- COMBINED ADDITIONS for P2-M11, P2-M12, P2-M10
====================================================================
CAPSTONE-189

PATCH BUNDLE, not a full file. This concatenates three append-only
patches, in the order they were produced, so they can be reviewed and
applied to the real shared/types.py as one pass instead of three
separate diffs. Each dataclass/enum below is otherwise UNCHANGED from
its original patch.

  Section 1 -- P2-M11 (AlertDeduplicator)   -- DedupResult
  Section 2 -- P2-M12 (CorrelationEngine)   -- EntityAttributesData
  Section 3 -- P2-M10 (AnomalyScorer)       -- Severity, EpisodeSearchResult,
                                                ScoringInput, AnomalyResult

Required imports for this whole bundle (add any not already present in
the real file's import block):

    from dataclasses import dataclass, field
    from datetime import datetime
    from enum import Enum
    from typing import Dict, Optional

------------------------------------------------------------------------
FLAG -- please confirm before applying
------------------------------------------------------------------------
The P2-M10 patch this bundle was built from states the real
shared/types.py, as of that upload, defines only:
RawRecord, EventBatch, EntityProfile, CurrentEmbedding, DeviationResult,
DriftScore.

That means, as far as the most recent snapshot of the real file shows:
  - DedupResult (Section 1) is NOT yet actually in the file -- it was
    handed to you as a standalone append patch earlier and may or may
    not have been applied since.
  - GroupType and CorrelationResult are ALSO not listed -- these were
    assumed already frozen/present (per the Project Directory Structure
    planning doc) when correlation_engine.py was written, and
    EntityAttributesData (Section 2) was added on that assumption
    without redefining them. If they're genuinely not in the real file
    yet, correlation_engine.py's `from shared.types import
    CorrelationResult, EntityAttributesData, GroupType` will fail on
    import until those two are added too -- say the word and I'll
    include them in this bundle.
  - Also note DriftScore (per this upload) vs. DriftResult (per the
    Directory Structure doc) -- a naming mismatch between the two
    sources, not something this bundle resolves.
------------------------------------------------------------------------
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


# =========================================================================
# Section 1 -- Alert Deduplication (P2-M11)
# =========================================================================

@dataclass
class DedupResult:
    """
    Output of AlertDeduplicator.check() (P2-M11). Wraps an AnomalyResult
    to signal whether it's a repeat firing within the dedup window for
    this entity, or a genuinely new incident.

    Parameters
    ----------
    entity_id:
        Unique identifier for the monitored resource.
    is_duplicate:
        True if an active (non-expired) fingerprint already existed for
        this entity's dedup window and matched this AnomalyResult's
        fingerprint. False starts a new tracked incident.
    canonical_incident_id:
        UUID4 identifying the incident this AnomalyResult belongs to --
        stable across repeated duplicate firings within the window.
    first_seen_ts:
        UTC timestamp of the FIRST AnomalyResult that opened this
        canonical_incident_id (not this particular firing's timestamp).
    recurrence_count:
        How many times (including this one) an AnomalyResult with a
        matching fingerprint has fired within the still-active window.
        Starts at 1 for a brand-new (non-duplicate) incident.
    """
    entity_id: str
    is_duplicate: bool
    canonical_incident_id: str
    first_seen_ts: datetime
    recurrence_count: int


# =========================================================================
# Section 2 -- Alert Correlation (P2-M12)
# =========================================================================
# Note: CorrelationResult and GroupType are assumed to already exist
# elsewhere in shared/types.py (per the Project Directory Structure
# doc) and are intentionally NOT redefined here -- see the FLAG at the
# top of this file if that assumption turns out to be wrong.

@dataclass
class EntityAttributesData:
    """
    The subset of an entity's identifying attributes CorrelationEngine
    needs to build graph edges. Sourced from whatever already tracks
    entity metadata (e.g. a small in-memory cache populated from
    RawRecord.region / .op_id / .cloud_provider as records are ingested,
    or a lookup against EntityStore if that's extended later) --
    CorrelationEngine itself does not care where it comes from, only
    that a BaseEntityAttributesProvider can produce one per entity_id.
    """
    entity_id: str
    cloud_provider: str
    region: str
    op_id: str


# =========================================================================
# Section 3 -- Final Anomaly Score (P2-M10)
# =========================================================================

class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class GroupType(str, Enum):
    ISOLATED = "ISOLATED"
    CORRELATED = "CORRELATED"
    REGIONAL_OUTAGE = "REGIONAL_OUTAGE"


@dataclass
class CorrelationResult:
    entity_id: str
    incident_group_id: str
    related_ids: List[str]
    group_size: int
    group_type: GroupType


@dataclass
class EpisodeSearchResult:
    """
    One historical episode match returned by EpisodeRetriever.search()
    (P2-M9). Added here (rather than only in a future P2-M9 PR) because
    AnomalyScorer's build_scoring_input() helper (P2-M10) needs the type
    to exist. If/when P2-M9 is merged through its own PR, treat that PR
    as canonical for this dataclass and drop it from here rather than
    maintaining two copies.

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
    List[EpisodeSearchResult] objects themselves -- matches the pure-
    function pattern P2-M7/M8/M9 already established, and the P2-M10
    ticket's own AI Prompt Brief verbatim.

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
