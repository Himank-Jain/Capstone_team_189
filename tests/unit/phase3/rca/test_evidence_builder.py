from __future__ import annotations

from datetime import datetime, timezone

from shared.types import AlertPayload, EpisodeMatch, GroupType, NotifyMethod, Severity, SevLevel
from phase3.rca.evidence_builder import EvidenceBuilder


def test_evidence_builder_assembles_case_from_alert_payload():
    payload = AlertPayload(
        alert_id="alert-123",
        entity_id="vm-001",
        batch_ts=datetime.now(timezone.utc),
        final_score=0.93,
        severity=Severity.CRITICAL,
        sev_level=SevLevel.SEV1,
        cloud_provider="AWS",
        region="us-east-1",
        deviation_score=0.81,
        drift_score=0.72,
        similarity_score=0.68,
        similar_episodes=[
            EpisodeMatch(
                similarity_score=0.80,
                episode_id="ep-1",
                entity_id="vm-001",
                timestamp=datetime.now(timezone.utc),
                cloud_provider="AWS",
                severity_label="HIGH",
            )
        ],
        related_ids=["inc-77"],
        group_type=GroupType.ISOLATED,
        target_team="platform",
        notify_method=NotifyMethod.SLACK,
    )

    rca = EvidenceBuilder().build(payload, tenant_id="tenant-7")

    assert rca.incident_id == "alert-123"
    assert rca.tenant_id == "tenant-7"
    assert rca.entity_id == "vm-001"
    assert len(rca.candidate_causes) >= 1
    assert rca.confidence in {"HIGH", "MEDIUM", "LOW"}
