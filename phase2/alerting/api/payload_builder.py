"""
phase2/alerting/api/payload_builder.py
==========================================
P2-M14  Explainable Alert API — payload assembly
CAPSTONE-189

Reduces the actual output types of P2-M10 (AnomalyResult), P2-M13
(EscalationResult), P2-M12 (CorrelationResult), and P2-M9
(EpisodeMatch/EpisodeSearchResult) into one AlertPayloadModel, matching
the reduction pattern anomaly_scorer.build_scoring_input() already
established for P2-M10's own inputs.

Import constraint
------------------
Only shared/types.py + this package's own models.py. Does NOT import
AnomalyScorer/CorrelationEngine/EscalationEngine themselves -- an
orchestrator one layer up (a future scripts/run_inference.py) is
responsible for calling those and passing their outputs here. Same
Low-Coupling rule already applied throughout phase2/alerting/.
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional, Sequence, Union

from shared.types import AnomalyResult, CorrelationResult, EpisodeMatch, EpisodeSearchResult, EscalationResult

from .models import AlertPayloadModel, EpisodeSummary

AnyEpisode = Union[EpisodeMatch, EpisodeSearchResult]


def _episode_to_summary(episode: AnyEpisode) -> EpisodeSummary:
    """Handles either EpisodeMatch or EpisodeSearchResult (see
    shared/types.py FLAG 3 -- both are kept live in the shared contract
    until P2-M9's own PR is canonical) without the caller needing to
    care which one it has."""
    return EpisodeSummary(
        similarity_score=episode.similarity_score,
        episode_id=episode.episode_id,
        entity_id=episode.entity_id,
        timestamp=episode.timestamp,
        cloud_provider=episode.cloud_provider,
        severity_label=episode.severity_label,
    )


def build_alert_payload(
    anomaly_result: AnomalyResult,
    escalation_result: EscalationResult,
    correlation_result: CorrelationResult,
    similar_episodes: Sequence[AnyEpisode],
    cloud_provider: str,
    region: str,
    alert_id: Optional[str] = None,
    contributing_features: Optional[List[str]] = None,
) -> AlertPayloadModel:
    """
    Assemble the terminal AlertPayloadModel P2-M14 dispatches.

    Parameters
    ----------
    anomaly_result:
        P2-M10 AnomalyScorer.score() output -- supplies final_score,
        severity, and the three raw component scores (recovered from
        the weighted contributions -- see _recover_component_scores).
    escalation_result:
        P2-M13 EscalationEngine.process() output -- supplies sev_level,
        target_team, notify_method.
    correlation_result:
        P2-M12 CorrelationEngine.process() output -- supplies
        group_type and related_ids.
    similar_episodes:
        P2-M9 EpisodeRetriever.search() output for this entity's
        current embedding.
    cloud_provider, region:
        Not present on AnomalyResult/EscalationResult/CorrelationResult
        (same "not smuggled onto the detection dataclasses" pattern
        P2-M12/P2-M13 both document) -- supplied by the caller, which
        already has them from the originating RawRecord/EntityProfile.
    alert_id:
        UUID4 string. Generated if omitted.
    contributing_features:
        Optional human-readable feature labels (e.g.
        ["cpu_utilization", "request_latency_p99"]) for the appended
        contributing_features field. Defaults to empty -- this module
        has no feature-importance computation of its own; an upstream
        caller with access to per-feature deviation can pass real
        labels here.

    Returns
    -------
    AlertPayloadModel
    """
    if anomaly_result.entity_id != escalation_result.entity_id:
        raise ValueError(
            f"[build_alert_payload] entity_id mismatch: "
            f"anomaly_result={anomaly_result.entity_id!r} "
            f"escalation_result={escalation_result.entity_id!r}"
        )
    if anomaly_result.entity_id != correlation_result.entity_id:
        raise ValueError(
            f"[build_alert_payload] entity_id mismatch: "
            f"anomaly_result={anomaly_result.entity_id!r} "
            f"correlation_result={correlation_result.entity_id!r}"
        )

    component_breakdown = _recover_component_scores(anomaly_result)

    return AlertPayloadModel(
        alert_id=uuid.UUID(alert_id) if alert_id else uuid.uuid4(),
        entity_id=anomaly_result.entity_id,
        batch_ts=anomaly_result.batch_ts,
        final_score=anomaly_result.final_score,
        severity=anomaly_result.severity,
        sev_level=escalation_result.sev_level,
        deviation_score=component_breakdown["deviation_score"],
        drift_score=component_breakdown["drift_score"],
        similarity_score=component_breakdown["similarity_score"],
        similar_episodes=[_episode_to_summary(e) for e in similar_episodes],
        related_ids=correlation_result.related_ids,
        group_type=correlation_result.group_type,
        target_team=escalation_result.target_team,
        notify_method=escalation_result.notify_method,
        cloud_provider=cloud_provider,
        region=region,
        component_breakdown=component_breakdown,
        contributing_features=contributing_features or [],
    )


def _recover_component_scores(anomaly_result: AnomalyResult) -> Dict[str, float]:
    """
    AnomalyResult only carries the WEIGHTED contributions
    (deviation_contribution etc.), not the raw [0,1] component scores
    AlertPayload's deviation_score/drift_score/similarity_score fields
    expect. Dividing back out by the weight recovers the raw score.
    Falls back to the raw contribution itself if the corresponding
    weight is zero (division would be meaningless/undefined) -- a
    misconfigured zero-weight formula shouldn't crash payload assembly.
    """
    from shared.constants import SCORE_W_DEVIATION, SCORE_W_DRIFT, SCORE_W_SIMILARITY

    deviation_score = (
        anomaly_result.deviation_contribution / SCORE_W_DEVIATION if SCORE_W_DEVIATION else anomaly_result.deviation_contribution
    )
    drift_score = (
        anomaly_result.drift_contribution / SCORE_W_DRIFT if SCORE_W_DRIFT else anomaly_result.drift_contribution
    )
    # similarity_contribution = w * (1 - similarity_score) => similarity_score = 1 - contribution/w
    similarity_score = (
        1.0 - (anomaly_result.similarity_contribution / SCORE_W_SIMILARITY)
        if SCORE_W_SIMILARITY
        else 1.0 - anomaly_result.similarity_contribution
    )
    return {
        "deviation_score": max(0.0, min(1.0, deviation_score)),
        "drift_score": max(0.0, min(1.0, drift_score)),
        "similarity_score": max(0.0, min(1.0, similarity_score)),
        "deviation_contribution": anomaly_result.deviation_contribution,
        "drift_contribution": anomaly_result.drift_contribution,
        "similarity_contribution": anomaly_result.similarity_contribution,
    }
