"""Deterministic confidence scoring for RCA hypotheses."""

from __future__ import annotations

from phase3.rca.types import CandidateCause, RCACase


class ConfidenceScorer:
    """Score a candidate cause using the evidence available on the case."""

    @staticmethod
    def score(candidate: CandidateCause, case: RCACase) -> str:
        if candidate.cause_category == "UNKNOWN":
            return "LOW"

        support_count = len(candidate.supporting_evidence_keys)
        contradiction_count = len(candidate.contradicting_evidence_keys)
        if support_count >= 2 and contradiction_count == 0:
            return "HIGH"
        if support_count >= 1 or case.final_score >= 0.65:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def score_case(case: RCACase) -> str:
        if not case.candidate_causes:
            return "LOW"
        ranked = sorted(
            case.candidate_causes,
            key=lambda candidate: {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(candidate.confidence, 0),
            reverse=True,
        )
        return ranked[0].confidence


__all__ = ["ConfidenceScorer"]
