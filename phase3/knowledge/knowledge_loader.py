"""Knowledge-base loader with validation and cached lookup."""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

import yaml

from phase3.knowledge.types import KnowledgeEntry, RecommendedCheck

PLACEHOLDER_WHITELIST = {
    "entity_id",
    "cloud_provider",
    "region",
    "final_score",
    "severity",
    "deviation_score",
    "drift_score",
    "similarity_score",
    "group_size",
    "top_changed_feature",
}


class KnowledgeLoader:
    """Load and validate the static knowledge base used by the guidance engine."""

    def __init__(self, path: str | Path | None = None):
        self._path = (
            Path(path) if path is not None else Path(__file__).with_name("knowledge_base.yaml")
        )
        self._cache: dict[str, KnowledgeEntry] = {}
        self._threat_cache: dict[str, dict[str, Any]] = {}
        self._data = self.load()

    def load(self) -> dict[str, Any]:
        with open(self._path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        self.validate_knowledge_base(data)
        self._cache = {}
        for entry in data.get("causes", []) or []:
            self._cache[entry["cause_category"]] = self._coerce_entry(entry, data)
        self._threat_cache = dict(data.get("threats") or {})
        return data

    def validate_knowledge_base(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise ValueError("knowledge base must be a mapping")
        self._validate_placeholders("knowledge base", data)
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
                raise ValueError(
                    f"knowledge entry '{cause.get('cause_category', 'unknown')}' "
                    f"missing required fields: {missing}"
                )
            for check in cause.get("recommended_checks", []) or []:
                if not all(key in check for key in ("check", "why", "expected_result", "risk")):
                    raise ValueError(
                        f"knowledge entry '{cause.get('cause_category', 'unknown')}' "
                        "has an incomplete recommended check"
                    )
        threats = data.get("threats")
        if threats is not None and not isinstance(threats, dict):
            raise ValueError("knowledge base 'threats' must be a mapping")
        public_ids: set[str] = set()
        for threat_id, threat in (threats or {}).items():
            required = (
                "public_id",
                "title",
                "definition",
                "how_it_shows_up",
                "typical_stages",
                "mitre_attack",
                "indicators_in_this_case",
                "investigative_checks",
                "mitigation",
                "false_positive_notes",
                "resolution_criteria",
                "limitations",
                "further_reading",
            )
            missing = [
                name
                for name in required
                if name not in threat
                or threat[name] is None
                or (isinstance(threat[name], str) and not threat[name].strip())
            ]
            if missing:
                raise ValueError(
                    f"threat entry '{threat_id}' missing required fields: {missing}"
                )
            if not isinstance(threat["public_id"], str) or not threat["public_id"].strip():
                raise ValueError(f"threat entry '{threat_id}' requires a public_id")
            public_id = threat["public_id"].strip()
            if public_id == threat_id or public_id in public_ids:
                raise ValueError(f"threat entry '{threat_id}' has a non-unique public_id")
            public_ids.add(public_id)
            for field_name in (
                "title",
                "definition",
                "how_it_shows_up",
                "false_positive_notes",
                "limitations",
            ):
                if not isinstance(threat[field_name], str) or not threat[field_name].strip():
                    raise ValueError(
                        f"threat entry '{threat_id}' requires non-empty text for {field_name}"
                    )
            for field_name in (
                "typical_stages",
                "indicators_in_this_case",
                "investigative_checks",
                "resolution_criteria",
                "further_reading",
            ):
                if not isinstance(threat[field_name], list) or not threat[field_name]:
                    raise ValueError(
                        f"threat entry '{threat_id}' requires a non-empty list for {field_name}"
                    )
            if not isinstance(threat["mitre_attack"], list):
                raise ValueError(f"threat entry '{threat_id}' mitre_attack must be a list")
            for check in threat.get("investigative_checks", []) or []:
                if not self._has_required_fields(
                    check, ("check", "why", "expected_result", "risk")
                ):
                    raise ValueError(f"threat entry '{threat_id}' has an incomplete check")
            for technique in threat.get("mitre_attack", []) or []:
                if not self._has_required_fields(technique, ("id", "name", "url")):
                    raise ValueError(f"threat entry '{threat_id}' has an incomplete ATT&CK mapping")
                if not str(technique["url"]).startswith(
                    "https://attack.mitre.org/techniques/"
                ):
                    raise ValueError(
                        f"threat entry '{threat_id}' has a non-official ATT&CK URL"
                    )
            for reading in threat.get("further_reading", []) or []:
                if not self._has_required_fields(reading, ("title", "url")):
                    raise ValueError(f"threat entry '{threat_id}' has incomplete further reading")
                if not str(reading["url"]).startswith("https://"):
                    raise ValueError(f"threat entry '{threat_id}' has an unverified reading URL")
            for phase in ("immediate", "short_term", "hardening"):
                steps = (threat.get("mitigation") or {}).get(phase)
                if not isinstance(steps, list) or not steps:
                    raise ValueError(
                        f"threat entry '{threat_id}' requires mitigation steps for {phase}"
                    )
                if any(not isinstance(step, dict) or not str(step.get("generic", "")).strip()
                       for step in steps):
                    raise ValueError(
                        f"threat entry '{threat_id}' has a mitigation step without generic text"
                    )
                for step in steps:
                    if set(step) - {"generic", "aws", "azure", "gcp", "oci"}:
                        raise ValueError(
                            f"threat entry '{threat_id}' has an unsupported mitigation variant"
                        )

    @staticmethod
    def _has_required_fields(value: Any, fields: tuple[str, ...]) -> bool:
        return isinstance(value, dict) and all(
            str(value.get(field, "")).strip() for field in fields
        )

    @staticmethod
    def _validate_placeholders(entry_id: str, entry: Any) -> None:
        if isinstance(entry, dict):
            values = list(entry.keys()) + list(entry.values())
        elif isinstance(entry, list):
            values = entry
        else:
            if isinstance(entry, str):
                KnowledgeLoader._validate_template(entry_id, entry)
            return
        for value in values:
            KnowledgeLoader._validate_placeholders(entry_id, value)

    @staticmethod
    def _validate_template(entry_id: str, value: str) -> None:
        for match in Template.pattern.finditer(value):
            if match.group("invalid") is not None:
                raise ValueError(f"knowledge entry '{entry_id}' has an invalid template")
            placeholder = match.group("named") or match.group("braced")
            if placeholder and placeholder not in PLACEHOLDER_WHITELIST:
                raise ValueError(
                    f"knowledge entry '{entry_id}' uses unapproved placeholder "
                    f"${placeholder}"
                )

    def retrieve_knowledge_entry(self, cause_category: str) -> KnowledgeEntry:
        category = (cause_category or "UNKNOWN").upper()
        if category in self._cache:
            return self._cache[category]
        return self._cache.get("UNKNOWN") or self._fallback_entry()

    def retrieve_threat_entry(self, threat_id: str) -> dict[str, Any] | None:
        entry = self._threat_cache.get(threat_id)
        return dict(entry) if entry is not None else None

    def public_threat_id(self, threat_id: str) -> str:
        entry = self.retrieve_threat_entry(threat_id)
        if entry is None:
            return "unclassified_threat_pattern"
        return str(entry["public_id"])

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
                    expected_result=(
                        "A clearer pattern emerges after reviewing the raw signal stream."
                    ),
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
        whitelist = {name: context.get(name, "") for name in PLACEHOLDER_WHITELIST}
        return Template(template).safe_substitute(whitelist)


__all__ = ["KnowledgeLoader", "PLACEHOLDER_WHITELIST"]
