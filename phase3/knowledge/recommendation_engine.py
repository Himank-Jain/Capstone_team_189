"""Recommendation engine for deterministic guidance checklists."""

from __future__ import annotations

from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.explanation_builder import ExplanationBuilder
from phase3.knowledge.threat_signature_matcher import ThreatSignatureMatcher
from phase3.knowledge.types import RecommendedCheck
from phase3.rca.types import RCACase


class RecommendationEngine:
    """Return the recommended checks for the top-ranked incident cause."""

    def __init__(
        self,
        loader: KnowledgeLoader | None = None,
        matcher: ThreatSignatureMatcher | None = None,
    ):
        self._loader = loader or KnowledgeLoader()
        self._matcher = matcher or ThreatSignatureMatcher()

    def recommend(self, rca_case: RCACase) -> list[RecommendedCheck]:
        candidate = self._top_candidate(rca_case)
        matches = self._matcher.match(rca_case)
        if matches:
            threat = self._loader.retrieve_threat_entry(matches[0].threat_id)
            if threat is not None:
                context = ExplanationBuilder._template_context(rca_case)
                return [
                    RecommendedCheck(
                        check=self._loader.template_value(item["check"], context),
                        why=self._loader.template_value(item["why"], context),
                        expected_result=self._loader.template_value(
                            item["expected_result"], context
                        ),
                        risk=str(item["risk"]),
                    )
                    for item in threat["investigative_checks"]
                ]
        entry = self._loader.retrieve_knowledge_entry(candidate.cause_category)
        checks = list(entry.recommended_checks)
        seen: set[str] = set()
        deduped: list[RecommendedCheck] = []
        for check in checks:
            key = f"{check.check}|{check.why}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(check)
        return deduped

    @staticmethod
    def _top_candidate(rca_case: RCACase):
        if not rca_case.candidate_causes:
            from phase3.rca.hypothesis_engine import HypothesisEngine

            return HypothesisEngine().generate(rca_case)[0]
        return sorted(
            rca_case.candidate_causes,
            key=lambda candidate: {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(candidate.confidence, 0),
            reverse=True,
        )[0]


__all__ = ["RecommendationEngine"]
