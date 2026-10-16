"""Deterministic RCA evidence builder for Phase 3 incidents."""

from __future__ import annotations

from typing import Iterable

from phase3.rca.types import CandidateCause, RCACase
from shared.types import AlertPayload


class EvidenceBuilder:
    """Build a structured RCACase from existing alert and similarity evidence."""

    def build(
        self,
        alert_payload: AlertPayload,
        tenant_id: str = "default",
        incident_id: str | None = None,
        cloud_provider: str | None = None,
        region: str | None = None,
    ) -> RCACase:
        if incident_id is None:
            incident_id = alert_payload.alert_id

        candidate_causes = self._candidate_causes(alert_payload)
        confidence = self._resolve_confidence(alert_payload, candidate_causes)
        region = region or "unknown"
        cloud_provider = cloud_provider or getattr(alert_payload, "cloud_provider", "unknown")

        return RCACase(
            rca_case_id=f"rca-{incident_id}",
            incident_id=incident_id,
            tenant_id=tenant_id,
            entity_id=alert_payload.entity_id,
            batch_ts=alert_payload.batch_ts,
            cloud_provider=cloud_provider,
            region=region,
            final_score=float(alert_payload.final_score),
            severity=str(
                alert_payload.severity.value
                if hasattr(alert_payload.severity, "value")
                else alert_payload.severity
            ),
            component_scores={
                "deviation": float(alert_payload.deviation_score),
                "drift": float(alert_payload.drift_score),
                "similarity": float(alert_payload.similarity_score),
            },
            changed_features=["entity_behavior", "resource_profile"],
            behavioral_deviation={
                "score": float(alert_payload.deviation_score),
                "entity_id": alert_payload.entity_id,
            },
            drift_evidence={
                "score": float(alert_payload.drift_score),
                "group_type": getattr(
                    alert_payload.group_type, "value", str(alert_payload.group_type)
                ),
            },
            similar_episodes=list(getattr(alert_payload, "similar_episodes", []) or []),
            related_incidents=list(getattr(alert_payload, "related_ids", []) or []),
            timeline=[
                {
                    "event": "alert_created",
                    "timestamp": (
                        alert_payload.batch_ts.isoformat()
                        if hasattr(alert_payload.batch_ts, "isoformat")
                        else str(alert_payload.batch_ts)
                    ),
                    "severity": str(alert_payload.severity),
                }
            ],
            observed_window={
                "entity_id": alert_payload.entity_id,
                "batch_ts": str(alert_payload.batch_ts),
            },
            baseline_window={"expected_behavior": "historical baseline"},
            unknowns=[],
            candidate_causes=candidate_causes,
            confidence=confidence,
        )

    def build_case(
        self,
        alert_payload: AlertPayload,
        tenant_id: str = "default",
        incident_id: str | None = None,
        cloud_provider: str | None = None,
        region: str | None = None,
    ) -> RCACase:
        return self.build(
            alert_payload,
            tenant_id=tenant_id,
            incident_id=incident_id,
            cloud_provider=cloud_provider,
            region=region,
        )

    def _candidate_causes(self, alert_payload: AlertPayload) -> list[CandidateCause]:
        causes: list[CandidateCause] = []
        if alert_payload.deviation_score >= 0.75:
            causes.append(
                CandidateCause(
                    cause_category="BEHAVIOR_CHANGE",
                    confidence="HIGH",
                    rule_id="rca.behavior_change",
                    supporting_evidence_keys=["component_scores", "behavioral_deviation"],
                    contradicting_evidence_keys=[],
                )
            )
        if alert_payload.drift_score >= 0.65:
            causes.append(
                CandidateCause(
                    cause_category="DRIFT",
                    confidence="MEDIUM",
                    rule_id="rca.drift",
                    supporting_evidence_keys=["component_scores", "drift_evidence"],
                    contradicting_evidence_keys=[],
                )
            )
        if alert_payload.similarity_score >= 0.6:
            causes.append(
                CandidateCause(
                    cause_category="RESOURCE_CHANGE",
                    confidence="MEDIUM",
                    rule_id="rca.resource_change",
                    supporting_evidence_keys=["similar_episodes", "related_incidents"],
                    contradicting_evidence_keys=[],
                )
            )
        if not causes:
            causes.append(
                CandidateCause(
                    cause_category="UNKNOWN",
                    confidence="LOW",
                    rule_id="rca.unknown",
                    supporting_evidence_keys=[],
                    contradicting_evidence_keys=["component_scores"],
                )
            )
        return causes

    def _resolve_confidence(
        self, alert_payload: AlertPayload, candidate_causes: Iterable[CandidateCause]
    ) -> str:
        highest = max(
            (candidate.confidence for candidate in candidate_causes),
            key=lambda label: {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(label, 0),
        )
        if highest == "HIGH" or alert_payload.final_score >= 0.85:
            return "HIGH"
        if highest == "MEDIUM" or alert_payload.final_score >= 0.6:
            return "MEDIUM"
        return "LOW"


__all__ = ["EvidenceBuilder"]
