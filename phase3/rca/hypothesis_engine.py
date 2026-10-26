"""Rule-based hypothesis engine for deterministic Phase 3 RCA classification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from phase3.rca.confidence_scorer import ConfidenceScorer
from phase3.rca.types import CandidateCause, RCACase

# Score-only categories that a matched threat signature should outrank.
_GENERIC_CATEGORIES = {"BEHAVIOR_CHANGE", "DRIFT", "RESOURCE_CHANGE", "UNKNOWN"}
# Signature keys look like "changed_features.api_calls.increase"; the prefix is
# the RCACase field that holds the supporting evidence.
_EVIDENCE_FIELDS = (
    "changed_features",
    "component_scores",
    "observed_window",
    "similar_episodes",
    "cloud_provider",
)


class HypothesisEngine:
    """First-match-wins hypothesis engine mirroring the escalation rule pattern."""

    def __init__(self, rules_path: str | Path | None = None, threat_matcher: Any = None):
        self._rules_path = (
            Path(rules_path)
            if rules_path is not None
            else Path(__file__).with_name("hypothesis_rules.yaml")
        )
        self._rules = self._load_rules(self._rules_path)
        self._threat_categories = self._load_threat_categories(self._rules_path)
        # Optional ThreatSignatureMatcher. Without one, only score rules apply.
        self._threat_matcher = threat_matcher

    @property
    def threat_categories(self) -> dict[str, str]:
        return dict(self._threat_categories)

    @staticmethod
    def _load_threat_categories(path: str | Path) -> dict[str, str]:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        mapping = data.get("threat_categories") or {}
        if not isinstance(mapping, dict):
            raise ValueError("threat_categories must map threat ids to cause categories")
        return {str(key): str(value).upper() for key, value in mapping.items()}

    @staticmethod
    def _load_rules(path: str | Path) -> list[dict[str, Any]]:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        rules = data.get("rules") or []
        if not isinstance(rules, list):
            raise ValueError("hypothesis rule file must contain a list of rules")
        return rules

    def generate(self, rca_case: RCACase) -> list[CandidateCause]:
        """Rank candidate causes: a matched threat signature, then the score rule."""
        return self.rank([self._rule_candidate(rca_case)], self.threat_candidate(rca_case))

    @staticmethod
    def rank(
        existing: list[CandidateCause], threat_candidate: CandidateCause | None
    ) -> list[CandidateCause]:
        """Merge a signature-based candidate into score-rule candidates."""
        if threat_candidate is None or not existing:
            return list(existing) or ([threat_candidate] if threat_candidate else [])
        top = existing[0]
        if top.cause_category == threat_candidate.cause_category:
            return list(existing)
        if top.cause_category not in _GENERIC_CATEGORIES:
            # A named-indicator rule fired; it stays first.
            return [*existing, threat_candidate]
        rest = [item for item in existing if item.cause_category != "UNKNOWN"]
        return [threat_candidate, *rest]

    def threat_candidate(self, rca_case: RCACase) -> CandidateCause | None:
        if self._threat_matcher is None or not self._threat_categories:
            return None
        match = next(
            (
                item
                for item in self._threat_matcher.match(rca_case)
                if item.match_confidence in {"HIGH", "MEDIUM"}
            ),
            None,
        )
        if match is None or match.threat_id not in self._threat_categories:
            return None
        supporting = []
        for key in match.matched_signal_keys:
            field = str(key).split(".", 1)[0]
            if field in _EVIDENCE_FIELDS and field not in supporting:
                supporting.append(field)
        return CandidateCause(
            cause_category=self._threat_categories[match.threat_id],
            confidence=match.match_confidence,
            # Named after the category, never the internal signature id, so
            # responses cannot echo the scenario that generated the data.
            rule_id=f"rca.threat_signature.{self._threat_categories[match.threat_id].lower()}",
            supporting_evidence_keys=supporting,
            contradicting_evidence_keys=[],
        )

    def _rule_candidate(self, rca_case: RCACase) -> CandidateCause:
        if not self._rules:
            return self._unknown_candidate()

        component_scores = rca_case.component_scores or {}
        scope = {"case": rca_case, "scores": component_scores}
        for rule in self._rules:
            condition = rule.get("condition")
            if condition is None:
                continue
            try:
                result = bool(eval(condition, {"__builtins__": {}}, scope))
            except Exception:
                result = False
            if result:
                candidate = CandidateCause(
                    cause_category=str(rule["cause_category"]),
                    confidence=str(rule.get("confidence", "LOW")),
                    rule_id=str(rule.get("id", "unknown")),
                    supporting_evidence_keys=list(rule.get("supporting_evidence_keys") or []),
                    contradicting_evidence_keys=list(rule.get("contradicting_evidence_keys") or []),
                )
                candidate.confidence = ConfidenceScorer.score(candidate, rca_case)
                return candidate

        return self._unknown_candidate()

    @staticmethod
    def _unknown_candidate() -> CandidateCause:
        return CandidateCause(
            cause_category="UNKNOWN",
            confidence="LOW",
            rule_id="rca.unknown",
            supporting_evidence_keys=[],
            contradicting_evidence_keys=["component_scores"],
        )


__all__ = ["HypothesisEngine"]
