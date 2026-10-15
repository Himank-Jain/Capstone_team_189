import socket
from datetime import datetime, timezone

from phase3.knowledge.explanation_builder import ExplanationBuilder
from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.recommendation_engine import RecommendationEngine
from phase3.knowledge.threat_signature_matcher import ThreatSignatureMatcher
from phase3.rca.types import RCACase


def test_knowledge_module_runs_without_network(monkeypatch):
    def reject_socket(*args, **kwargs):
        raise AssertionError("knowledge guidance must not open a network socket")

    monkeypatch.setattr(socket, "socket", reject_socket)

    loader = KnowledgeLoader()
    case = RCACase(
        rca_case_id="rca-local",
        incident_id="incident-local",
        tenant_id="tenant-local",
        entity_id="entity-local",
        batch_ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        cloud_provider="AWS",
        region="us-east-1",
        final_score=0.2,
        severity="LOW",
        component_scores={},
    )

    explanation = ExplanationBuilder(loader).build(case)
    recommendations = RecommendationEngine(loader).recommend(case)
    matches = ThreatSignatureMatcher().match(case)

    assert explanation.cause_category == "UNKNOWN"
    assert explanation.is_fallback is True
    assert recommendations
    assert matches == []

    case.changed_features = [
        "metric_family:api_calls",
        "metric_family:auth_failures",
    ]
    case.observed_window = {
        "metric_directions": {
            "api_calls": "increase",
            "auth_failures": "increase",
        }
    }
    matched_explanation = ExplanationBuilder(loader).build(case)
    matched_checks = RecommendationEngine(loader).recommend(case)

    assert matched_explanation.mitigation_mode == "threat_specific"
    assert matched_explanation.matched_threats[0].match_confidence in {"MEDIUM", "HIGH"}
    assert matched_checks
