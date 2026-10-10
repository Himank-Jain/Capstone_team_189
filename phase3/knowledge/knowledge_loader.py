"""Knowledge-base loader with validation and cached lookup."""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

import yaml

from phase3.knowledge.types import KnowledgeEntry, RecommendedCheck


class KnowledgeLoader:
    """Load and validate the static knowledge base used by the guidance engine."""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path is not None else Path(__file__).with_name("knowledge_base.yaml")
        self._cache: dict[str, KnowledgeEntry] = {}
        self._data = self.load()

    def load(self) -> dict[str, Any]:
        with open(self._path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        self.validate_knowledge_base(data)
        self._cache = {}
        for entry in data.get("causes", []) or []:
            self._cache[entry["cause_category"]] = self._coerce_entry(entry, data)
        return data

    def validate_knowledge_base(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise ValueError("knowledge base must be a mapping")
        causes = data.get("causes") or []
        if not isinstance(causes, list) or not causes:
            raise ValueError("knowledge base requires a non-empty 'causes' list")
        for cause in causes:
            required = [
                "cause_category",
                "title",
                "definition",
                "how_it_shows_up",
                "common_causes",
                "why_it_matters",
                "recommended_checks",
                "limitations",
                "further_reading",
            ]
            missing = [name for name in required if not cause.get(name)]
            if missing:
                raise ValueError(f"knowledge entry '{cause.get('cause_category', 'unknown')}' missing required fields: {missing}")
            for check in cause.get("recommended_checks", []) or []:
                if not all(key in check for key in ("check", "why", "expected_result", "risk")):
                    raise ValueError(f"knowledge entry '{cause.get('cause_category', 'unknown')}' has an incomplete recommended check")

    def retrieve_knowledge_entry(self, cause_category: str) -> KnowledgeEntry:
        category = (cause_category or "UNKNOWN").upper()
        if category in self._cache:
            return self._cache[category]
        return self._cache.get("UNKNOWN") or self._fallback_entry()

    def _coerce_entry(self, entry: dict[str, Any], data: dict[str, Any]) -> KnowledgeEntry:
        checks = [
            RecommendedCheck(
                check=str(item.get("check", "")),
                why=str(item.get("why", "")),
                expected_result=str(item.get("expected_result", "")),
                risk=str(item.get("risk", "LOW")),
            )
            for item in entry.get("recommended_checks", []) or []
        ]
        return KnowledgeEntry(
            cause_category=str(entry["cause_category"]),
            title=str(entry["title"]),
            definition=str(entry["definition"]),
            how_it_shows_up=str(entry["how_it_shows_up"]),
            common_causes=[str(item) for item in entry.get("common_causes", []) or []],
            why_it_matters=str(entry["why_it_matters"]),
            recommended_checks=checks,
            limitations=str(entry["limitations"]),
            further_reading=str(entry["further_reading"]),
            signal_glossary=list(entry.get("signal_glossary") or []),
            confidence_note=(data.get("confidence_levels") or {}).get("HIGH"),
            extra={"kb_version": data.get("kb_version", "unknown")},
        )

    def _fallback_entry(self) -> KnowledgeEntry:
        return KnowledgeEntry(
            cause_category="UNKNOWN",
            title="Unknown or insufficient evidence",
            definition="This case does not match the current deterministic knowledge map.",
            how_it_shows_up="The available evidence was insufficient to classify confidently.",
            common_causes=["Insufficient telemetry", "Transient issue"],
            why_it_matters="Unknown cases should remain conservative until the cause is validated.",
            recommended_checks=[
                RecommendedCheck(
                    check="Review the last 2-4 hours of telemetry",
                    why="More signal is needed to reach a confident classification.",
                    expected_result="A clearer pattern emerges after reviewing the raw signal stream.",
                    risk="MEDIUM",
                )
            ],
            limitations="This is a conservative fallback path.",
            further_reading="Collect more evidence before making a confident call.",
            confidence_note="Evidence is limited.",
            extra={"kb_version": "unknown"},
        )

    @staticmethod
    def template_value(template: str, context: dict[str, Any]) -> str:
        whitelist = {
            "case": context.get("case"),
            "candidate": context.get("candidate"),
            "tenant_id": context.get("tenant_id"),
            "entity_id": context.get("entity_id"),
            "final_score": context.get("final_score"),
            "severity": context.get("severity"),
        }
        return Template(template).safe_substitute(whitelist)


__all__ = ["KnowledgeLoader"]
