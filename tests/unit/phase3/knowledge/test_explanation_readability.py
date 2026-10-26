"""Explanations are analyst-facing text: no float noise, raw keys, or Python reprs."""

import re
from datetime import datetime, timezone

from phase3.knowledge.explanation_builder import ExplanationBuilder, describe_signal
from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.types import ThreatMatch
from phase3.rca.types import CandidateCause, RCACase


class _Matcher:
    def match(self, _case):
        return [
            ThreatMatch(
                threat_id="credential_theft",
                match_confidence="HIGH",
                matched_signal_keys=[
                    "changed_features.api_calls.increase",
                    "observed_window.entity_types",
                    "component_scores.deviation",
                ],
                unmatched_signal_keys=["similar_episodes.severity"],
            )
        ]


def _case(candidate_keys):
    return RCACase(
        rca_case_id="rca-1",
        incident_id="incident-1",
        tenant_id="google",
        entity_id="vol-g00g",
        batch_ts=datetime(2026, 10, 26, tzinfo=timezone.utc),
        cloud_provider="GCP",
        region="us-central1",
        final_score=0.7081234,
        severity="HIGH",
        component_scores={"deviation": 0.736, "drift": 0.6759999999999999, "similarity": 0.28},
        changed_features=["metric_family:api_calls", "metric_family:auth_failures"],
        behavioral_deviation={"score": 0.736, "entity_id": "vol-g00g"},
        drift_evidence={"score": 0.6759999999999999, "group_type": "ISOLATED"},
        observed_window={"metric_directions": {"api_calls": "increase", "auth_failures": "increase"}},
        candidate_causes=[
            CandidateCause(
                cause_category="DRIFT",
                confidence="MEDIUM",
                rule_id="rca.drift",
                supporting_evidence_keys=candidate_keys,
                contradicting_evidence_keys=[],
            )
        ],
        confidence="MEDIUM",
    )


def _all_text(explanation):
    return "\n".join(
        [explanation.headline, explanation.match_basis]
        + [section.body for section in explanation.sections]
        + [s for threat in explanation.matched_threats for s in threat.matched_signals]
    )


def test_threat_explanation_has_no_float_noise_raw_keys_or_reprs():
    explanation = ExplanationBuilder(KnowledgeLoader(), _Matcher()).build(
        _case(["component_scores", "drift_evidence", "changed_features"])
    )
    text = _all_text(explanation)

    assert not re.search(r"\d\.\d{4,}", text), "scores should be rounded"
    assert "{'" not in text and "'}" not in text
    assert "changed_features." not in text
    assert "observed_window." not in text
    assert "api calls increased" in text
    assert "Drift score 0.68 (correlation group ISOLATED)" in text
    assert "api calls (increase), auth failures (increase)" in text


def test_list_sections_are_one_item_per_line():
    explanation = ExplanationBuilder(KnowledgeLoader(), _Matcher()).build(_case(["component_scores"]))
    sections = {section.heading: section.body for section in explanation.sections}

    assert sections["Investigative checks"].startswith("1. ")
    assert "\n2. " in sections["Investigative checks"]
    assert sections["Typical stages"].startswith("1. ")
    assert all(" — https://" in line for line in sections["Further reading"].splitlines())
    assert len(sections["Read-only mitigation guidance"].splitlines()) >= 3


def test_describe_signal():
    assert describe_signal("changed_features.auth_failures.decrease") == "auth failures decreased"
    assert describe_signal("component_scores.drift") == "drift score is in the pattern's range"
    assert describe_signal("cloud_provider") == "cloud provider is in scope for the pattern"
