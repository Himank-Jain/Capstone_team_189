from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from phase3.knowledge.explanation_builder import ExplanationBuilder
from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.types import ThreatMatch
from phase3.rca.types import CandidateCause, RCACase

PROVIDERS = ("AWS", "Azure", "GCP", "OCI")
KNOWLEDGE_BASE = Path(__file__).parents[4] / "phase3" / "knowledge" / "knowledge_base.yaml"
THREATS = yaml.safe_load(KNOWLEDGE_BASE.read_text(encoding="utf-8"))["threats"]


class _FixedMatcher:
    def __init__(self, threat_id: str, confidence: str = "HIGH"):
        self.threat_id = threat_id
        self.confidence = confidence

    def match(self, _case):
        return [
            ThreatMatch(
                threat_id=self.threat_id,
                match_confidence=self.confidence,
                matched_signal_keys=["changed_features.api_calls.increase"],
                unmatched_signal_keys=["changed_features.auth_failures.increase"],
            )
        ]


def _case(provider: str, entity_id: str = "resource-a") -> RCACase:
    return RCACase(
        rca_case_id="rca-provider-matrix",
        incident_id="incident-provider-matrix",
        tenant_id="tenant-a",
        entity_id=entity_id,
        batch_ts=datetime(2026, 10, 14, tzinfo=timezone.utc),
        cloud_provider=provider,
        region="us-east-1",
        final_score=0.82,
        severity="HIGH",
        component_scores={"deviation": 0.8, "drift": 0.6, "similarity": 0.2},
        changed_features=["metric_family:api_calls"],
        observed_window={"metric_directions": {"api_calls": "increase"}},
        candidate_causes=[
            CandidateCause(
                cause_category="BEHAVIOR_CHANGE",
                confidence="HIGH",
                rule_id="test.behavior",
                supporting_evidence_keys=["changed_features"],
                contradicting_evidence_keys=[],
            )
        ],
    )


@pytest.mark.parametrize("threat_id", sorted(THREATS))
@pytest.mark.parametrize("provider", PROVIDERS)
def test_threat_explanation_provider_variants_are_generated(threat_id, provider):
    loader = KnowledgeLoader()
    threat = THREATS[threat_id]
    explanation = ExplanationBuilder(
        loader, _FixedMatcher(threat_id)
    ).build(_case(provider))
    guidance = next(
        section.body
        for section in explanation.sections
        if section.heading == "Read-only mitigation guidance"
    )
    context = ExplanationBuilder._template_context(_case(provider))

    assert explanation.mitigation_mode == "threat_specific"
    assert explanation.matched_threats[0].threat_id == threat["public_id"]
    for phase in ("immediate", "short_term", "hardening"):
        for step in threat["mitigation"][phase]:
            expected = loader.template_value(
                step.get(provider.casefold()) or step["generic"], context
            )
            assert expected in guidance


def test_low_confidence_threat_match_keeps_generic_explanation():
    explanation = ExplanationBuilder(
        KnowledgeLoader(), _FixedMatcher("credential_theft", "LOW")
    ).build(_case("AWS"))

    assert explanation.mitigation_mode == "generic"
    assert explanation.cause_category == "BEHAVIOR_CHANGE"
    assert explanation.matched_threats[0].match_confidence == "LOW"
    assert any(section.heading == "Common causes" for section in explanation.sections)


def test_hostile_resource_placeholder_is_rendered_inertly():
    explanation = ExplanationBuilder(
        KnowledgeLoader(), _FixedMatcher("credential_theft")
    ).build(_case("AWS", entity_id="${severity}"))
    rendered = " ".join(section.body for section in explanation.sections)

    assert "${severity}" in rendered
    assert "for LOW" not in rendered
