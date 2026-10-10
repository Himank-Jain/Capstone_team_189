"""Build deterministic explanations from the knowledge base."""

from __future__ import annotations

from typing import Any

from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.types import Explanation, ExplanationSection
from phase3.rca.types import RCACase


class ExplanationBuilder:
    """Creates a consistent explanation for the currently top-ranked cause."""

    def __init__(self, loader: KnowledgeLoader | None = None):
        self._loader = loader or KnowledgeLoader()

    def build(self, rca_case: RCACase) -> Explanation:
        candidate = self._top_candidate(rca_case)
        entry = self._loader.retrieve_knowledge_entry(candidate.cause_category)
        kb_version = entry.extra.get("kb_version") or "unknown"
        sections = [
            ExplanationSection("Summary", entry.title),
            ExplanationSection("What this means", entry.definition),
            ExplanationSection("How it was detected", entry.how_it_shows_up),
            ExplanationSection("Common causes", "; ".join(entry.common_causes) if entry.common_causes else entry.definition),
            ExplanationSection("Why it matters", entry.why_it_matters),
            ExplanationSection("Evidence for this case", self._collect_case_evidence(rca_case, candidate)),
            ExplanationSection("Limitations", entry.limitations),
        ]
        headline = entry.title
        return Explanation(
            rca_case_id=rca_case.rca_case_id,
            cause_category=candidate.cause_category,
            headline=headline,
            sections=sections,
            kb_version=str(kb_version),
            is_fallback=candidate.cause_category == "UNKNOWN",
        )

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

    @staticmethod
    def _collect_case_evidence(rca_case: RCACase, candidate: Any) -> str:
        details = []
        for key in candidate.supporting_evidence_keys:
            if key == "component_scores":
                details.append(f"component_scores={rca_case.component_scores}")
            elif key == "changed_features":
                details.append(f"changed_features={rca_case.changed_features}")
            elif key == "behavioral_deviation":
                details.append(f"behavioral_deviation={rca_case.behavioral_deviation}")
            elif key == "drift_evidence":
                details.append(f"drift_evidence={rca_case.drift_evidence}")
            elif key == "similar_episodes":
                details.append(f"similar_episodes={rca_case.similar_episodes}")
            elif key == "related_incidents":
                details.append(f"related_incidents={rca_case.related_incidents}")
        if not details:
            return f"final_score={rca_case.final_score}; severity={rca_case.severity}; confidence={rca_case.confidence}"
        return "; ".join(details)


__all__ = ["ExplanationBuilder"]
