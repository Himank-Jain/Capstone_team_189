"""Recommendation engine for deterministic guidance checklists."""

from __future__ import annotations

from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.types import RecommendedCheck
from phase3.rca.types import RCACase


class RecommendationEngine:
    """Return the recommended checks for the top-ranked incident cause."""

    def __init__(self, loader: KnowledgeLoader | None = None):
        self._loader = loader or KnowledgeLoader()

    def recommend(self, rca_case: RCACase) -> list[RecommendedCheck]:
        candidate = self._top_candidate(rca_case)
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
