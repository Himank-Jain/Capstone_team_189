"""Build deterministic explanations from the knowledge base."""

from __future__ import annotations

from typing import Any

from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.threat_signature_matcher import ThreatSignatureMatcher
from phase3.knowledge.types import Explanation, ExplanationSection, MatchedThreat
from phase3.rca.types import RCACase

_SIGNAL_LABELS = {
    "observed_window.entity_types": "resource type fits the pattern",
    "observed_window.namespaces": "telemetry namespace fits the pattern",
    "cloud_provider": "cloud provider is in scope for the pattern",
    "similar_episodes.severity": "similar past episodes with a matching severity",
}


def _fmt(value: Any) -> str:
    """Render scores the way an analyst reads them (two decimals, no float noise)."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}"
    return str(value)


def describe_signal(key: str) -> str:
    """Turn a signature key such as changed_features.api_calls.increase into prose."""
    parts = str(key).split(".")
    if len(parts) == 3 and parts[0] == "changed_features":
        direction = "increased" if parts[2] == "increase" else "decreased"
        return f"{parts[1].replace('_', ' ')} {direction}"
    if len(parts) == 2 and parts[0] == "component_scores":
        return f"{parts[1]} score is in the pattern's range"
    return _SIGNAL_LABELS.get(key, str(key).replace("_", " ").replace(".", " "))


def _lines(items: list[str], numbered: bool = False) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if numbered:
        return "\n".join(f"{index}. {item}" for index, item in enumerate(cleaned, start=1))
    return "\n".join(cleaned)


class ExplanationBuilder:
    """Creates a consistent explanation for the currently top-ranked cause."""

    def __init__(
        self,
        loader: KnowledgeLoader | None = None,
        matcher: ThreatSignatureMatcher | None = None,
    ):
        self._loader = loader or KnowledgeLoader()
        self._matcher = matcher or ThreatSignatureMatcher()

    def build(self, rca_case: RCACase) -> Explanation:
        threat_matches = self._matcher.match(rca_case)
        candidate = self._top_candidate(rca_case)
        entry = self._loader.retrieve_knowledge_entry(candidate.cause_category)
        kb_version = entry.extra.get("kb_version") or "unknown"
        matched_threats = self._matched_threats(threat_matches)
        threat_match = next(
            (
                match
                for match in threat_matches
                if match.match_confidence in {"MEDIUM", "HIGH"}
            ),
            None,
        )
        threat = (
            self._loader.retrieve_threat_entry(threat_match.threat_id)
            if threat_match is not None
            else None
        )
        if threat is not None:
            return self._build_threat_explanation(
                rca_case,
                candidate,
                threat_match,
                threat,
                str(kb_version),
                matched_threats,
            )
        sections = [
            ExplanationSection("Summary", entry.title),
            ExplanationSection("What this means", entry.definition),
            ExplanationSection("How it was detected", entry.how_it_shows_up),
            ExplanationSection(
                "Common causes",
                _lines(entry.common_causes) if entry.common_causes else entry.definition,
            ),
            ExplanationSection("Why it matters", entry.why_it_matters),
            ExplanationSection(
                "Evidence for this case", self._collect_case_evidence(rca_case, candidate)
            ),
            ExplanationSection("Limitations", entry.limitations),
        ]
        headline = entry.title
        return Explanation(
            rca_case_id=rca_case.rca_case_id,
            cause_category=entry.cause_category,
            headline=headline,
            sections=sections,
            kb_version=str(kb_version),
            is_fallback=entry.cause_category == "UNKNOWN",
            matched_threats=matched_threats,
            match_basis=self._match_basis(threat_matches),
            mitigation_mode="generic",
        )

    def _build_threat_explanation(
        self, rca_case, candidate, match, threat, kb_version, matched_threats
    ):
        context = self._template_context(rca_case)
        mitigation = threat["mitigation"]
        controls = self._provider_controls(mitigation, rca_case.cloud_provider)
        check_text = _lines(
            [
                f"{self._render(check['check'], context)} "
                f"(Expected: {self._render(check['expected_result'], context)})"
                for check in threat["investigative_checks"]
            ],
            numbered=True,
        )
        mitigation_text = _lines(
            [
                f"{phase.replace('_', ' ').title()}: {self._render(step, context)}"
                for phase, steps in controls.items()
                for step in steps
            ]
        )
        mitre_text = _lines(
            [f"{item['id']} — {item['name']}" for item in threat["mitre_attack"]]
        ) or (
            "No technique mapping is included because the evidence does not support "
            "a verified mapping."
        )
        observed = [describe_signal(key) for key in match.matched_signal_keys]
        missing = [describe_signal(key) for key in match.unmatched_signal_keys]
        evidence_lines = [
            f"Pattern match confidence: {match.match_confidence}",
            "Observed: " + ("; ".join(observed) or "none"),
            "Not observed: " + ("; ".join(missing) or "none"),
            self._collect_case_evidence(rca_case, candidate),
        ]
        sections = [
            ExplanationSection("What this means", self._render(threat["definition"], context)),
            ExplanationSection(
                "How it may show up",
                self._render(threat["how_it_shows_up"], context),
            ),
            ExplanationSection(
                "Typical stages",
                _lines([self._render(stage, context) for stage in threat["typical_stages"]], numbered=True),
            ),
            ExplanationSection("Evidence for this case", _lines(evidence_lines)),
            ExplanationSection("Investigative checks", check_text),
            ExplanationSection("Read-only mitigation guidance", mitigation_text),
            ExplanationSection("MITRE ATT&CK context", mitre_text),
            ExplanationSection(
                "False-positive considerations",
                self._render(threat["false_positive_notes"], context),
            ),
            ExplanationSection("Limitations", self._render(threat["limitations"], context)),
            ExplanationSection(
                "Resolution criteria",
                _lines([self._render(item, context) for item in threat["resolution_criteria"]]),
            ),
            ExplanationSection(
                "Further reading",
                _lines(
                    [
                        f"{self._render(item.get('title') or 'Reference', context)} — "
                        f"{self._render(item['url'], context)}"
                        for item in threat["further_reading"]
                    ]
                ),
            ),
        ]
        return Explanation(
            rca_case_id=rca_case.rca_case_id,
            cause_category=candidate.cause_category,
            headline=self._render(threat["title"], context),
            sections=sections,
            kb_version=kb_version,
            is_fallback=candidate.cause_category == "UNKNOWN" and threat is None,
            matched_threats=matched_threats,
            match_basis=self._match_basis([match]),
            mitigation_mode="threat_specific",
        )

    def _matched_threats(self, matches) -> list[MatchedThreat]:
        result = []
        for match in matches:
            threat = self._loader.retrieve_threat_entry(match.threat_id)
            result.append(
                MatchedThreat(
                    threat_id=self._loader.public_threat_id(match.threat_id),
                    title=str(threat.get("title") or "Unclassified threat pattern")
                    if threat
                    else "Unclassified threat pattern",
                    match_confidence=match.match_confidence,
                    matched_signals=[describe_signal(key) for key in match.matched_signal_keys],
                    unmatched_signals=[
                        describe_signal(key) for key in match.unmatched_signal_keys
                    ],
                )
            )
        return result

    @staticmethod
    def _match_basis(matches) -> str:
        if not matches:
            return ""
        metrics = []
        for signal in matches[0].matched_signal_keys:
            parts = signal.split(".")
            if len(parts) == 3 and parts[0] == "changed_features":
                metric_name = parts[1].replace("_", " ")
                direction = "increased" if parts[2] == "increase" else "decreased"
                metrics.append(f"{metric_name} {direction}")
        if not metrics:
            return "Available case evidence overlaps the versioned threat signature."
        if len(metrics) == 1:
            return f"The observed {metrics[0]}."
        return "The observed " + ", ".join(metrics[:-1]) + " and " + metrics[-1] + "."

    @staticmethod
    def _provider_controls(mitigation, cloud_provider: str):
        provider_key = cloud_provider.casefold()
        result = {}
        for phase, steps in mitigation.items():
            result[phase] = [
                step.get(provider_key) or step["generic"]
                for step in steps
            ]
        return result

    @staticmethod
    def _template_context(rca_case: RCACase) -> dict[str, Any]:
        features = [str(feature) for feature in rca_case.changed_features]
        top_feature = features[0] if features else ""
        parts = top_feature.split(":")
        observed_window = rca_case.observed_window or {}
        return {
            "entity_id": rca_case.entity_id,
            "cloud_provider": rca_case.cloud_provider,
            "region": rca_case.region,
            "final_score": _fmt(rca_case.final_score),
            "severity": rca_case.severity,
            "deviation_score": _fmt(rca_case.component_scores.get("deviation", "")),
            "drift_score": _fmt(rca_case.component_scores.get("drift", "")),
            "similarity_score": _fmt(rca_case.component_scores.get("similarity", "")),
            "group_size": len(rca_case.similar_episodes),
            "top_changed_feature": parts[1] if len(parts) > 1 else top_feature,
            "top_changed_direction": parts[2] if len(parts) > 2 else "",
            "window_start": observed_window.get("window_start", rca_case.batch_ts.isoformat()),
            "window_end": observed_window.get("window_end", rca_case.batch_ts.isoformat()),
            "related_count": len(rca_case.related_incidents),
        }

    def _render(self, value: Any, context: dict[str, Any]) -> str:
        return self._loader.template_value(str(value), context)

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
        details = [
            f"Final score {_fmt(rca_case.final_score)} ({rca_case.severity}); "
            f"RCA confidence {rca_case.confidence}"
        ]
        directions = (rca_case.observed_window or {}).get("metric_directions") or {}
        for key in candidate.supporting_evidence_keys:
            if key == "component_scores":
                scores = ", ".join(
                    f"{name} {_fmt(value)}" for name, value in rca_case.component_scores.items()
                )
                details.append(f"Component scores: {scores or 'none recorded'}")
            elif key == "changed_features":
                features = []
                for feature in rca_case.changed_features:
                    parts = str(feature).split(":")
                    name = parts[1] if len(parts) > 1 and parts[0] == "metric_family" else str(feature)
                    direction = parts[2] if len(parts) > 2 else directions.get(name, "")
                    label = name.replace("_", " ")
                    features.append(f"{label} ({direction})" if direction else label)
                details.append("Changed features: " + (", ".join(features) or "none"))
            elif key == "behavioral_deviation":
                score = (rca_case.behavioral_deviation or {}).get("score")
                details.append(f"Behavioral deviation score {_fmt(score) if score is not None else 'not recorded'}")
            elif key == "drift_evidence":
                drift = rca_case.drift_evidence or {}
                group = drift.get("group_type")
                score = drift.get("score")
                text = f"Drift score {_fmt(score) if score is not None else 'not recorded'}"
                details.append(f"{text} (correlation group {group})" if group else text)
            elif key == "similar_episodes":
                details.append(f"{len(rca_case.similar_episodes)} similar past episode(s)")
            elif key == "related_incidents":
                details.append(f"{len(rca_case.related_incidents)} related incident(s)")
        return "\n".join(details)


__all__ = ["ExplanationBuilder"]
