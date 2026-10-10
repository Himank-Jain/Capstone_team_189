"""
phase2/alerting/api/models.py
==========================================
P2-M14  Explainable Alert API — request/response models
CAPSTONE-189

Pydantic models for the terminal alert delivery API. These are the
JSON-facing counterparts of the frozen shared/types.py dataclasses
(Section 5 / P2-M13's own AlertPayload) -- FastAPI needs Pydantic
models for request validation + OpenAPI docs, and shared/types.py is
deliberately kept dataclass-only (no Pydantic/FastAPI dependency leaks
into shared/, which every phase imports) per the project's Low Coupling
rule.

Design notes — deviations from the literal ticket text, and why
------------------------------------------------------------------
1. Field names match the FROZEN shared.types.AlertPayload, not the AI
   Prompt Brief's alternate names. The brief asks for
   "component_breakdown", "similar_incidents", "related_incidents",
   "escalation_team" and a bare "severity" Enum(Sev1-4). The frozen
   dataclass (Directory Structure Section 5, already implemented and
   consumed nowhere else in Sev1-4 form) instead has: severity: Severity
   (LOW/MEDIUM/HIGH/CRITICAL, the anomaly-score band) *and*
   sev_level: SevLevel (SEV1-4, the escalation tier) as two DISTINCT
   fields -- not one Enum wearing two hats. It also names the episode
   list similar_episodes (List[EpisodeMatch]) and the incident list
   related_ids (List[str]), and has no escalation_team field, only
   target_team. This module keeps every frozen name as-is (same
   precedent as escalation_engine.py's policy_applied /
   GroupType.REGIONAL_OUTAGE decisions) and ADDS the two genuinely new,
   non-overlapping explainability fields the brief wants on top:
   component_breakdown (per-component contribution weights, distinct
   from deviation/drift/similarity_score which are the raw *inputs*)
   and contributing_features (human-readable feature labels, distinct
   from similar_episodes' AnomalyResult-level detail). Both are appended
   with defaults, non-breaking to any code already constructing
   AlertPayload positionally -- same append-only pattern P2-M13 used
   for business_hours_flag.

2. EpisodeSummary vs EpisodeMatch. Rather than re-exporting the shared
   dataclass directly into a FastAPI response (dataclasses serialize
   fine via Pydantic's `arbitrary_types_allowed`, but give worse OpenAPI
   schema output), EpisodeSummary is a thin Pydantic mirror of
   EpisodeMatch's fields. `from_episode_match()` converts one to the
   other so callers upstream (anything importing EpisodeMatch /
   EpisodeSearchResult from shared/types.py) never need to import
   Pydantic themselves.

3. severity / sev_level as plain strings on the wire. Pydantic v2 with
   `use_enum_values` would silently coerce these away from the shared
   Enum types if imported directly; instead this module accepts the
   shared Severity / SevLevel / GroupType / NotifyMethod enums directly
   as field types (Pydantic natively supports str-Enum members), so
   `AlertPayloadModel(...).severity` is still a real `Severity` member
   in Python, not a bare string -- only the JSON wire format is a string.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from shared.types import EpisodeMatch, GroupType, NotifyMethod, Severity, SevLevel


class EpisodeSummary(BaseModel):
    """Pydantic mirror of shared.types.EpisodeMatch (design note 2)."""

    similarity_score: float
    episode_id: str
    entity_id: str
    timestamp: Optional[datetime] = None
    cloud_provider: str
    severity_label: Optional[str] = None

    @classmethod
    def from_episode_match(cls, match: EpisodeMatch) -> "EpisodeSummary":
        return cls(
            similarity_score=match.similarity_score,
            episode_id=match.episode_id,
            entity_id=match.entity_id,
            timestamp=match.timestamp,
            cloud_provider=match.cloud_provider,
            severity_label=match.severity_label,
        )


class AlertPayloadModel(BaseModel):
    """
    Wire-format / request-body counterpart of shared.types.AlertPayload.
    See module docstring, design note 1, for the two appended fields
    (component_breakdown, contributing_features) not present on the
    frozen dataclass.
    """

    alert_id: UUID
    entity_id: str
    batch_ts: datetime
    final_score: float = Field(ge=0.0, le=1.0)
    severity: Severity
    sev_level: SevLevel
    deviation_score: float
    drift_score: float
    similarity_score: float
    similar_episodes: List[EpisodeSummary] = Field(default_factory=list)
    related_ids: List[str] = Field(default_factory=list)
    group_type: GroupType
    target_team: str
    notify_method: NotifyMethod
    cloud_provider: str
    region: str

    # Appended explainability fields — see design note 1.
    component_breakdown: Dict[str, float] = Field(default_factory=dict)
    contributing_features: List[str] = Field(default_factory=list)

    model_config = {"use_enum_values": False}


class DispatchOutcome(BaseModel):
    """Per-channel result of one notifier's dispatch attempt."""

    channel: str
    success: bool
    detail: str = ""
    latency_ms: Optional[float] = None


class AlertDispatchResponse(BaseModel):
    """Response body for POST /alert."""

    alert_id: UUID
    entity_id: str
    dispatch_status: Dict[str, DispatchOutcome]
    all_succeeded: bool
