from datetime import datetime

import pytest

from phase3.identity.membership_validator import MembershipValidator
from phase3.knowledge.explanation_builder import ExplanationBuilder
from phase3.knowledge.recommendation_engine import RecommendationEngine
from phase3.rca.hypothesis_engine import HypothesisEngine
from phase3.rca.types import RCACase
from phase3.security.audit_logger import AuditLogger
from phase3.security.middleware import TenantIsolationMiddleware
from shared.types import AlertPayload, GroupType, NotifyMethod, Severity, SevLevel


@pytest.fixture
def sample_rca_case() -> RCACase:
    return RCACase(
        rca_case_id="rca-1",
        incident_id="incident-1",
        tenant_id="tenant-a",
        entity_id="vm-1",
        batch_ts=datetime(2026, 10, 9, 12, 0, 0),
        cloud_provider="AWS",
        region="us-east-1",
        final_score=0.92,
        severity="CRITICAL",
        component_scores={"deviation": 0.9, "drift": 0.2, "similarity": 0.11},
        changed_features=["cpu_usage"],
        behavioral_deviation={"score": 0.9},
        drift_evidence={"score": 0.2},
        similar_episodes=[],
        related_incidents=[],
        timeline=[],
        observed_window={"window": "last_2h"},
        baseline_window={"window": "previous_7d"},
        unknowns=[],
        candidate_causes=[],
        confidence="HIGH",
    )


@pytest.fixture
def alert_payload() -> AlertPayload:
    return AlertPayload(
        alert_id="alert-1",
        entity_id="vm-1",
        batch_ts=datetime(2026, 10, 9, 12, 0, 0),
        final_score=0.92,
        severity=Severity.CRITICAL,
        sev_level=SevLevel.SEV1,
        deviation_score=0.9,
        drift_score=0.2,
        similarity_score=0.11,
        similar_episodes=[],
        related_ids=[],
        group_type=GroupType.ISOLATED,
        target_team="sre",
        notify_method=NotifyMethod.EMAIL,
    )


def test_hypothesis_engine_selects_high_confidence_behavior_change(sample_rca_case):
    hypothesis = HypothesisEngine()
    candidates = hypothesis.generate(sample_rca_case)

    assert candidates
    assert candidates[0].cause_category == "BEHAVIOR_CHANGE"
    assert candidates[0].confidence in {"HIGH", "MEDIUM"}


def test_knowledge_builder_returns_explanation_and_recommendations(sample_rca_case):
    explanation = ExplanationBuilder().build(sample_rca_case)
    recommendations = RecommendationEngine().recommend(sample_rca_case)

    assert explanation.cause_category == "BEHAVIOR_CHANGE"
    assert explanation.sections
    assert explanation.kb_version
    assert recommendations
    assert all(getattr(item, "check", None) for item in recommendations)


@pytest.mark.parametrize(
    ("features", "category"),
    [
        (["iam_policy_change", "suspicious_login_location", "credential_reset_spike"], "CREDENTIAL_THEFT"),
        (["file_access_spike", "privilege_escalation_attempt", "new_data_exfiltration_pattern"], "PRIVILEGE_ESCALATION"),
        (["port_scan_count", "new_ip_discovery", "lateral_probe_burst"], "NETWORK_RECONNAISSANCE"),
    ],
)
def test_attack_feature_sets_select_specific_hypothesis(sample_rca_case, features, category):
    sample_rca_case.final_score = 0.82
    sample_rca_case.changed_features = features

    candidate = HypothesisEngine().generate(sample_rca_case)[0]

    assert candidate.cause_category == category
    assert candidate.confidence == "HIGH"


def test_every_hypothesis_category_has_knowledge_entry():
    from phase3.knowledge.knowledge_loader import KnowledgeLoader

    rule_categories = {
        rule["cause_category"] for rule in HypothesisEngine()._rules
    }
    knowledge_categories = {
        entry["cause_category"]
        for entry in KnowledgeLoader()._data["causes"]
    }

    assert rule_categories <= knowledge_categories


def test_tenant_isolation_rejects_cross_tenant_access():
    class FakeMembershipReader:
        def fetch_membership(self, user_id, tenant_id):
            return {("u-1", "tenant-a"): type("M", (), {"role": "OWNER"})()}.get((user_id, tenant_id))

    middleware = TenantIsolationMiddleware(MembershipValidator(FakeMembershipReader()))

    class Request:
        def __init__(self):
            self.session = {"user_id": "u-1", "tenant_id": "tenant-a"}

    class Response:
        pass

    assert middleware.authorize(Request(), "tenant-a") is True
    with pytest.raises(PermissionError):
        middleware.authorize(Request(), "tenant-b")

    logger = AuditLogger()
    event = logger.record("u-1", "tenant-a", "view", "/rca/incident-1")
    assert event["tenant_id"] == "tenant-a"
    assert event["action"] == "view"
