"""Deterministic knowledge-base utilities for Phase 3 explanation and guidance."""

from phase3.knowledge.explanation_builder import ExplanationBuilder
from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.recommendation_engine import RecommendationEngine
from phase3.knowledge.threat_signature_matcher import ThreatSignatureMatcher
from phase3.knowledge.types import (
    Explanation,
    ExplanationSection,
    KnowledgeEntry,
    RecommendedCheck,
    ThreatMatch,
)

__all__ = [
    "Explanation",
    "ExplanationBuilder",
    "ExplanationSection",
    "KnowledgeEntry",
    "KnowledgeLoader",
    "RecommendationEngine",
    "RecommendedCheck",
    "ThreatMatch",
    "ThreatSignatureMatcher",
]
