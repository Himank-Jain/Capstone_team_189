"""Deterministic matching of RCACase evidence to versioned threat signatures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from phase3.knowledge.types import ThreatMatch
from phase3.rca.types import RCACase


class ThreatSignatureMatcher:
    """Score static threat signatures against evidence already present in an RCACase."""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path is not None else Path(__file__).with_name(
            "threat_signatures.yaml"
        )
        self._signatures = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        with self._path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        signatures = data.get("signatures") if isinstance(data, dict) else None
        if not isinstance(signatures, list) or not signatures:
            raise ValueError("threat signatures require a non-empty 'signatures' list")

        loaded: dict[str, dict[str, Any]] = {}
        for signature in signatures:
            if not isinstance(signature, dict):
                raise ValueError("each threat signature must be a mapping")
            threat_id = signature.get("threat_id")
            conditions = signature.get("conditions")
            minimum_score = signature.get("minimum_score")
            if (
                not isinstance(threat_id, str)
                or not threat_id
                or not isinstance(conditions, dict)
                or not isinstance(minimum_score, int)
                or minimum_score < 1
            ):
                raise ValueError(f"invalid threat signature: {threat_id!r}")
            if threat_id in loaded:
                raise ValueError(f"duplicate threat signature: {threat_id}")
            unknown_conditions = set(conditions) - {
                "metric_signals",
                "entity_types",
                "namespaces",
                "cloud_providers",
                "component_patterns",
                "similar_episode_severities",
            }
            if unknown_conditions:
                raise ValueError(
                    f"unknown conditions in threat signature {threat_id}: "
                    f"{sorted(unknown_conditions)}"
                )
            metric_conditions = conditions.get("metric_signals", []) or []
            if not isinstance(metric_conditions, list) or not metric_conditions:
                raise ValueError(f"threat signature requires metric signals: {threat_id}")
            for condition in metric_conditions:
                if (
                    not isinstance(condition, dict)
                    or not condition.get("metric_family")
                    or condition.get("direction") not in {"increase", "decrease"}
                    or not self._valid_weight(condition.get("weight"))
                ):
                    raise ValueError(f"invalid metric condition in threat signature: {threat_id}")
            for condition_name in ("entity_types", "namespaces", "cloud_providers"):
                condition = conditions.get(condition_name)
                if condition is not None and (
                    not isinstance(condition, dict)
                    or not isinstance(condition.get("any_of"), list)
                    or not condition["any_of"]
                    or not self._valid_weight(condition.get("weight"))
                ):
                    raise ValueError(f"invalid {condition_name} condition: {threat_id}")
            for condition in conditions.get("component_patterns", []) or []:
                if not isinstance(condition, dict):
                    raise ValueError(f"invalid component condition: {threat_id}")
                minimum = condition.get("minimum")
                maximum = condition.get("maximum")
                if (
                    condition.get("score") not in {"deviation", "drift", "similarity"}
                    or not self._valid_weight(condition.get("weight"))
                    or (minimum is None and maximum is None)
                    or (minimum is not None and not isinstance(minimum, (int, float)))
                    or (maximum is not None and not isinstance(maximum, (int, float)))
                    or (
                        minimum is not None
                        and maximum is not None
                        and minimum > maximum
                    )
                ):
                    raise ValueError(f"invalid component condition: {threat_id}")
            severity_condition = conditions.get("similar_episode_severities")
            if severity_condition is not None and (
                not isinstance(severity_condition, dict)
                or not isinstance(severity_condition.get("any_of"), list)
                or not self._valid_weight(severity_condition.get("weight"))
            ):
                raise ValueError(f"invalid episode-severity condition: {threat_id}")
            loaded[threat_id] = signature
        return loaded

    @staticmethod
    def _valid_weight(value: Any) -> bool:
        return isinstance(value, int) and value > 0

    def match(self, rca_case: RCACase) -> list[ThreatMatch]:
        """Return up to three above-threshold matches in deterministic rank order."""
        ranked: list[tuple[int, str, ThreatMatch]] = []
        for threat_id, signature in self._signatures.items():
            matched, unmatched, score, evidence_kinds = self._score_case(
                rca_case, signature["conditions"]
            )
            if score < signature["minimum_score"] or "metric" not in evidence_kinds:
                continue
            confidence = self._confidence(score, evidence_kinds)
            ranked.append(
                (
                    score,
                    threat_id,
                    ThreatMatch(
                        threat_id=threat_id,
                        match_confidence=confidence,
                        matched_signal_keys=matched,
                        unmatched_signal_keys=unmatched,
                    ),
                )
            )
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked[:3]]

    def _score_case(
        self, rca_case: RCACase, conditions: dict[str, Any]
    ) -> tuple[list[str], list[str], int, set[str]]:
        matched: list[str] = []
        unmatched: list[str] = []
        evidence_kinds: set[str] = set()
        score = 0
        evidence = rca_case.observed_window or {}
        features = self._feature_evidence(
            rca_case.changed_features, evidence.get("metric_directions") or {}
        )

        for condition in conditions.get("metric_signals", []) or []:
            family = str(condition["metric_family"])
            direction = str(condition["direction"])
            key = f"changed_features.{family}.{direction}"
            if features.get(family) == direction:
                matched.append(key)
                score += condition["weight"]
                evidence_kinds.add("metric")
            else:
                unmatched.append(key)

        for name, field in (
            ("entity_types", "entity_types"),
            ("namespaces", "namespaces"),
        ):
            condition = conditions.get(name)
            if condition is None:
                continue
            observed = set(evidence.get(field) or [])
            key = f"observed_window.{field}"
            if observed.intersection(condition["any_of"]):
                matched.append(key)
                score += condition["weight"]
                evidence_kinds.add(name)
            else:
                unmatched.append(key)

        provider_condition = conditions.get("cloud_providers")
        if provider_condition is not None:
            key = "cloud_provider"
            if rca_case.cloud_provider in provider_condition["any_of"]:
                matched.append(key)
                score += provider_condition["weight"]
                evidence_kinds.add("provider")
            else:
                unmatched.append(key)

        for condition in conditions.get("component_patterns", []) or []:
            component = float(rca_case.component_scores.get(condition["score"], 0.0))
            minimum = condition.get("minimum")
            maximum = condition.get("maximum")
            key = f"component_scores.{condition['score']}"
            if (
                (minimum is None or component >= float(minimum))
                and (maximum is None or component <= float(maximum))
            ):
                matched.append(key)
                score += condition["weight"]
                evidence_kinds.add("component")
            else:
                unmatched.append(key)

        severity_condition = conditions.get("similar_episode_severities")
        if severity_condition is not None:
            severities = {
                str(episode.get("severity", "")).upper()
                for episode in rca_case.similar_episodes
                if isinstance(episode, dict)
            }
            key = "similar_episodes.severity"
            if severities.intersection(
                {str(value).upper() for value in severity_condition["any_of"]}
            ):
                matched.append(key)
                score += severity_condition["weight"]
                evidence_kinds.add("correlation")
            else:
                unmatched.append(key)
        return matched, unmatched, score, evidence_kinds

    @staticmethod
    def _feature_evidence(
        changed_features: list[str], metric_directions: dict[str, str]
    ) -> dict[str, str]:
        evidence: dict[str, str] = {}
        for feature in changed_features:
            parts = str(feature).split(":")
            if len(parts) >= 2 and parts[0] == "metric_family":
                if len(parts) >= 3:
                    evidence[parts[1]] = parts[2]
                elif parts[1] in metric_directions:
                    evidence[parts[1]] = metric_directions[parts[1]]
        return evidence

    @staticmethod
    def _confidence(score: int, evidence_kinds: set[str]) -> str:
        if score >= 6 and "metric" in evidence_kinds and "component" in evidence_kinds:
            return "HIGH"
        if score >= 4:
            return "MEDIUM"
        return "LOW"


__all__ = ["ThreatSignatureMatcher"]
