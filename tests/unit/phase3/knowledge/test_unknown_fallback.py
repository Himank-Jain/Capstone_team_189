from datetime import datetime, timezone
from pathlib import Path

import pytest

from phase3.knowledge.explanation_builder import ExplanationBuilder
from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.recommendation_engine import RecommendationEngine
from phase3.rca.types import CandidateCause, RCACase


@pytest.fixture
def rca_case():
    return RCACase(
        rca_case_id="rca-fallback",
        incident_id="incident-fallback",
        tenant_id="tenant-a",
        entity_id="entity-a",
        batch_ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        cloud_provider="AWS",
        region="us-east-1",
        final_score=0.2,
        severity="LOW",
        component_scores={},
    )


@pytest.mark.parametrize("candidate_category", [None, "NOT_A_KNOWN_CATEGORY"])
def test_unknown_cases_use_populated_fallback(candidate_category, rca_case):
    if candidate_category is not None:
        rca_case.candidate_causes = [
            CandidateCause(
                cause_category=candidate_category,
                confidence="HIGH",
                rule_id="test.unknown",
                supporting_evidence_keys=[],
                contradicting_evidence_keys=[],
            )
        ]

    loader = KnowledgeLoader()
    explanation = ExplanationBuilder(loader).build(rca_case)
    recommendations = RecommendationEngine(loader).recommend(rca_case)

    assert explanation.cause_category == "UNKNOWN"
    assert explanation.is_fallback is True
    assert recommendations
    assert all(
        check.check.strip()
        and check.why.strip()
        and check.expected_result.strip()
        and check.risk.strip()
        for check in recommendations
    )


def test_broken_knowledge_base_fails_during_load():
    fixture_path = Path(__file__).with_name("fixtures") / "broken_knowledge_base.yaml"

    with pytest.raises(ValueError, match="missing required fields"):
        KnowledgeLoader(fixture_path)
