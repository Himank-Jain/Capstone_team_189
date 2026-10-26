"""Threat-signature evidence turns into a ranked, knowledge-backed RCA category."""

from datetime import datetime, timezone

from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.threat_signature_matcher import ThreatSignatureMatcher
from phase3.knowledge.types import ThreatMatch
from phase3.rca.hypothesis_engine import HypothesisEngine
from phase3.rca.types import RCACase


class _Matcher:
    def __init__(self, *matches):
        self._matches = list(matches)

    def match(self, _case):
        return self._matches


def _match(threat_id, confidence="HIGH"):
    return ThreatMatch(
        threat_id=threat_id,
        match_confidence=confidence,
        matched_signal_keys=["changed_features.api_calls.increase", "component_scores.deviation"],
        unmatched_signal_keys=["similar_episodes.severity"],
    )


def _case(final_score=0.57, deviation=0.59, drift=0.54, similarity=0.4):
    return RCACase(
        rca_case_id="rca-1",
        incident_id="incident-1",
        tenant_id="acme",
        entity_id="vol-acme",
        batch_ts=datetime(2026, 10, 26, tzinfo=timezone.utc),
        cloud_provider="AWS",
        region="us-west-2",
        final_score=final_score,
        severity="MEDIUM",
        component_scores={"deviation": deviation, "drift": drift, "similarity": similarity},
        changed_features=["metric_family:api_calls"],
        behavioral_deviation={},
        drift_evidence={},
        similar_episodes=[],
        related_incidents=[],
        timeline=[],
        observed_window={},
        baseline_window={},
        unknowns=[],
        candidate_causes=[],
        confidence="LOW",
    )


def test_matched_signature_replaces_unknown_with_a_real_category():
    candidates = HypothesisEngine(threat_matcher=_Matcher(_match("credential_theft"))).generate(_case())

    assert [c.cause_category for c in candidates] == ["IDENTITY_MISUSE"]
    assert candidates[0].confidence == "HIGH"
    assert candidates[0].rule_id == "rca.threat_signature.identity_misuse"
    assert candidates[0].supporting_evidence_keys == ["changed_features", "component_scores"]


def test_signature_ranks_ahead_of_generic_score_rule_which_is_kept():
    candidates = HypothesisEngine(threat_matcher=_Matcher(_match("ransomware"))).generate(
        _case(final_score=0.86, deviation=0.9)
    )

    assert [c.cause_category for c in candidates] == ["DESTRUCTIVE_ACTIVITY", "BEHAVIOR_CHANGE"]


def test_low_confidence_or_unmapped_matches_are_ignored():
    low = HypothesisEngine(threat_matcher=_Matcher(_match("credential_theft", "LOW"))).generate(_case())
    unmapped = HypothesisEngine(threat_matcher=_Matcher(_match("ambiguous_change"))).generate(_case())
    no_matcher = HypothesisEngine().generate(_case())

    assert [c.cause_category for c in low] == ["UNKNOWN"]
    assert [c.cause_category for c in unmapped] == ["UNKNOWN"]
    assert [c.cause_category for c in no_matcher] == ["UNKNOWN"]


def test_every_mapped_category_and_signature_exists():
    engine = HypothesisEngine()
    knowledge = set(KnowledgeLoader()._cache)
    signatures = set(ThreatSignatureMatcher()._signatures)

    assert set(engine.threat_categories.values()) <= knowledge
    assert set(engine.threat_categories) <= signatures


def _stored_case(changed, directions):
    return {
        "rca_case_id": "rca-old", "incident_id": "old", "tenant_id": "acme", "entity_id": "vol-acme",
        "batch_ts": "2026-10-26T17:00:00+00:00", "cloud_provider": "AWS", "region": "us-west-2",
        "final_score": 0.57, "severity": "MEDIUM",
        "component_scores": {"deviation": 0.59, "drift": 0.54, "similarity": 0.4},
        "changed_features": changed, "behavioral_deviation": {}, "drift_evidence": {},
        "similar_episodes": [], "related_incidents": [], "timeline": [],
        "observed_window": {"entity_types": ["Instances"], "namespaces": ["CWAgent"], "metric_directions": directions},
        "baseline_window": {}, "unknowns": [], "confidence": "LOW",
        "candidate_causes": [{
            "cause_category": "UNKNOWN", "confidence": "LOW", "rule_id": "rca.unknown",
            "supporting_evidence_keys": [], "contradicting_evidence_keys": ["component_scores"],
        }],
    }


def test_stored_unknown_incident_is_backfilled_from_signature_evidence():
    from phase3.api.routers._support import refresh_case_hypotheses

    stored = _stored_case(
        ["metric_family:api_calls", "metric_family:auth_failures"],
        {"api_calls": "increase", "auth_failures": "increase"},
    )
    refreshed = refresh_case_hypotheses(stored)

    assert refreshed["candidate_causes"][0]["cause_category"] == "IDENTITY_MISUSE"
    assert refreshed["confidence"] == "HIGH"
    assert stored["candidate_causes"][0]["cause_category"] == "UNKNOWN", "input is not mutated"


def test_stored_case_without_signature_evidence_is_unchanged():
    from phase3.api.routers._support import refresh_case_hypotheses

    stored = _stored_case(["entity_behavior"], {})
    assert refresh_case_hypotheses(stored) is stored
