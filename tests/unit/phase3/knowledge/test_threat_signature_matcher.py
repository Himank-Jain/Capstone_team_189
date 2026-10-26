from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import yaml
import pytest

from phase3.knowledge.threat_signature_matcher import ThreatSignatureMatcher
from phase3.knowledge.explanation_builder import ExplanationBuilder
from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.recommendation_engine import RecommendationEngine
from phase3.rca.types import RCACase


def _make_case(data):
    return RCACase(
        **{
            **data,
            "batch_ts": datetime.fromisoformat(data["batch_ts"]),
        }
    )


def test_matcher_matches_golden_cases_exactly():
    fixture = Path(__file__).with_name("fixtures") / "threat_matcher_golden.yaml"
    golden_cases = yaml.safe_load(fixture.read_text(encoding="utf-8"))["cases"]
    matcher = ThreatSignatureMatcher()

    for golden in golden_cases:
        actual = [
            asdict(match)
            for match in matcher.match(_make_case(golden["rca_case"]))
        ]
        assert actual == golden["expected"], golden["name"]


def test_correlation_only_evidence_never_produces_a_threat_match():
    case = RCACase(
        rca_case_id="rca-correlation-only",
        incident_id="incident-correlation-only",
        tenant_id="tenant-a",
        entity_id="entity-a",
        batch_ts=datetime(2026, 1, 1),
        cloud_provider="AWS",
        region="us-east-1",
        final_score=0.9,
        severity="CRITICAL",
        component_scores={},
        similar_episodes=[{"severity": "CRITICAL"}],
    )

    assert ThreatSignatureMatcher().match(case) == []


def test_direction_mismatch_does_not_match_a_metric_signature():
    case = RCACase(
        rca_case_id="rca-direction",
        incident_id="incident-direction",
        tenant_id="tenant-a",
        entity_id="entity-a",
        batch_ts=datetime(2026, 1, 1),
        cloud_provider="AWS",
        region="us-east-1",
        final_score=0.9,
        severity="CRITICAL",
        component_scores={"deviation": 0.9, "drift": 0.8},
        changed_features=["metric_family:storage_write_ops:decrease"],
        observed_window={
            "entity_types": ["Buckets"],
            "namespaces": ["AWS/EBS"],
        },
    )

    assert not any(
        match.threat_id == "ransomware" for match in ThreatSignatureMatcher().match(case)
    )


def test_metric_direction_is_read_without_changing_feature_strings(tmp_path):
    fixture = tmp_path / "signatures.yaml"
    fixture.write_text(
        yaml.safe_dump(
            {
                "signatures": [
                    {
                        "threat_id": "api-activity",
                        "minimum_score": 1,
                        "conditions": {
                            "metric_signals": [
                                {
                                    "metric_family": "api_calls",
                                    "direction": "increase",
                                    "weight": 1,
                                }
                            ]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    case = RCACase(
        rca_case_id="rca-preserved-feature-contract",
        incident_id="incident-preserved-feature-contract",
        tenant_id="tenant-a",
        entity_id="entity-a",
        batch_ts=datetime(2026, 1, 1),
        cloud_provider="AWS",
        region="us-east-1",
        final_score=0.5,
        severity="MEDIUM",
        component_scores={},
        changed_features=["metric_family:api_calls"],
        observed_window={"metric_directions": {"api_calls": "increase"}},
    )

    matches = ThreatSignatureMatcher(fixture).match(case)

    assert [match.threat_id for match in matches] == ["api-activity"]


def test_injected_signature_file_is_validated_and_results_are_capped_at_three(tmp_path):
    fixture = tmp_path / "signatures.yaml"
    fixture.write_text(
        yaml.safe_dump(
            {
                "signatures": [
                    {
                        "threat_id": threat_id,
                        "minimum_score": 1,
                        "conditions": {
                            "metric_signals": [
                                {
                                    "metric_family": "api_calls",
                                    "direction": "increase",
                                    "weight": 1,
                                }
                            ]
                        },
                    }
                    for threat_id in ("alpha", "bravo", "charlie", "delta")
                ]
            }
        ),
        encoding="utf-8",
    )
    case = RCACase(
        rca_case_id="rca-top-three",
        incident_id="incident-top-three",
        tenant_id="tenant-a",
        entity_id="entity-a",
        batch_ts=datetime(2026, 1, 1),
        cloud_provider="AWS",
        region="us-east-1",
        final_score=0.5,
        severity="MEDIUM",
        component_scores={},
        changed_features=["metric_family:api_calls:increase"],
    )

    matches = ThreatSignatureMatcher(fixture).match(case)

    assert [match.threat_id for match in matches] == ["alpha", "bravo", "charlie"]
    assert all(match.match_confidence == "LOW" for match in matches)


def test_invalid_injected_signature_file_fails_at_startup(tmp_path):
    fixture = tmp_path / "invalid_signatures.yaml"
    fixture.write_text("signatures: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty 'signatures' list"):
        ThreatSignatureMatcher(fixture)


def test_matched_threat_drives_hedged_explanation_and_targeted_checks():
    fixture = Path(__file__).with_name("fixtures") / "threat_matcher_golden.yaml"
    golden = yaml.safe_load(fixture.read_text(encoding="utf-8"))["cases"][0]
    case = _make_case(golden["rca_case"])
    loader = KnowledgeLoader()
    matcher = ThreatSignatureMatcher()

    explanation = ExplanationBuilder(loader, matcher).build(case)
    checks = RecommendationEngine(loader, matcher).recommend(case)

    assert explanation.headline == "Possible cloud credential misuse"
    assert explanation.kb_version == "2.2.0"
    assert "credential_theft" not in explanation.headline
    assert any(section.heading == "MITRE ATT&CK context" for section in explanation.sections)
    assert checks
    assert all(
        check.check and check.why and check.expected_result and check.risk for check in checks
    )
