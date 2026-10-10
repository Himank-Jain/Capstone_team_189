"""Phase 3 RCA model types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List


@dataclass
class CandidateCause:
    cause_category: str
    confidence: str
    rule_id: str
    supporting_evidence_keys: List[str]
    contradicting_evidence_keys: List[str]


@dataclass
class RCACase:
    rca_case_id: str
    incident_id: str
    tenant_id: str
    entity_id: str
    batch_ts: datetime
    cloud_provider: str
    region: str
    final_score: float
    severity: str
    component_scores: dict[str, float]
    changed_features: List[str] = field(default_factory=list)
    behavioral_deviation: dict[str, Any] = field(default_factory=dict)
    drift_evidence: dict[str, Any] = field(default_factory=dict)
    similar_episodes: List[Any] = field(default_factory=list)
    related_incidents: List[str] = field(default_factory=list)
    timeline: List[dict[str, Any]] = field(default_factory=list)
    observed_window: dict[str, Any] = field(default_factory=dict)
    baseline_window: dict[str, Any] = field(default_factory=dict)
    unknowns: List[str] = field(default_factory=list)
    candidate_causes: List[CandidateCause] = field(default_factory=list)
    confidence: str = "LOW"
    statistical_evidence: dict[str, Any] | None = None


__all__ = ["CandidateCause", "RCACase"]
