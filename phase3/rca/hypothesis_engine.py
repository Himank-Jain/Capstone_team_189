"""Rule-based hypothesis engine for deterministic Phase 3 RCA classification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from phase3.rca.confidence_scorer import ConfidenceScorer
from phase3.rca.types import CandidateCause, RCACase


class HypothesisEngine:
    """First-match-wins hypothesis engine mirroring the escalation rule pattern."""

    def __init__(self, rules_path: str | Path | None = None):
        self._rules_path = (
            Path(rules_path)
            if rules_path is not None
            else Path(__file__).with_name("hypothesis_rules.yaml")
        )
        self._rules = self._load_rules(self._rules_path)

    @staticmethod
    def _load_rules(path: str | Path) -> list[dict[str, Any]]:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        rules = data.get("rules") or []
        if not isinstance(rules, list):
            raise ValueError("hypothesis rule file must contain a list of rules")
        return rules

    def generate(self, rca_case: RCACase) -> list[CandidateCause]:
        if not self._rules:
            return [self._unknown_candidate()]

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
                return [candidate]

        return [self._unknown_candidate()]

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
