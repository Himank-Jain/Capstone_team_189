"""Knowledge-base contracts for deterministic guidance and explanations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecommendedCheck:
    check: str
    why: str
    expected_result: str
    risk: str


@dataclass
class ExplanationSection:
    heading: str
    body: str


@dataclass
class Explanation:
    rca_case_id: str
    cause_category: str
    headline: str
    sections: list[ExplanationSection] = field(default_factory=list)
    kb_version: str = "unknown"
    is_fallback: bool = False


@dataclass
class KnowledgeEntry:
    cause_category: str
    title: str
    definition: str
    how_it_shows_up: str
    common_causes: list[str]
    why_it_matters: str
    recommended_checks: list[RecommendedCheck]
    limitations: str
    further_reading: str
    signal_glossary: list[dict[str, str]] = field(default_factory=list)
    confidence_note: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


__all__ = ["RecommendedCheck", "ExplanationSection", "Explanation", "KnowledgeEntry"]
