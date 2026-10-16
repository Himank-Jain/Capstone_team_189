"""Build deterministic explanations from the knowledge base."""

from __future__ import annotations

from typing import Any

from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.threat_signature_matcher import ThreatSignatureMatcher
from phase3.knowledge.types import Explanation, ExplanationSection, MatchedThreat
from phase3.rca.types import RCACase


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
                "; ".join(entry.common_causes) if entry.common_causes else entry.definition,
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
        check_text = "\n".join(
            f"{index}. {self._render(check['check'], context)} "
            f"(Expected: {self._render(check['expected_result'], context)})"
            for index, check in enumerate(threat["investigative_checks"], start=1)
        )
        mitigation_text = "\n".join(
            f"{phase.replace('_', ' ').title()}: "
            + "; ".join(self._render(step, context) for step in steps)
            for phase, steps in controls.items()
        )
        mitre_text = "; ".join(
            f"{item['id']} — {item['name']}" for item in threat["mitre_attack"]
        ) or (
            "No technique mapping is included because the evidence does not support "
            "a verified mapping."
        )
        indicators = ", ".join(threat["indicators_in_this_case"])
        evidence = self._collect_case_evidence(rca_case, candidate)
        sections = [
            ExplanationSection("What this means", self._render(threat["definition"], context)),
            ExplanationSection(
                "How it may show up",
                self._render(threat["how_it_shows_up"], context),
            ),
            ExplanationSection(
                "Typical stages",
                "; ".join(self._render(stage, context) for stage in threat["typical_stages"]),
            ),
            ExplanationSection(
                "Evidence for this case",
                f"Signature match confidence: {match.match_confidence}. "
                f"Signals: {', '.join(match.matched_signal_keys) or 'none'}; "
                f"not observed: {', '.join(match.unmatched_signal_keys) or 'none'}. "
                f"Relevant RCACase fields: {indicators}. {evidence}",
            ),
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
                "; ".join(
                    self._render(item, context) for item in threat["resolution_criteria"]
                ),
            ),
            ExplanationSection(
                "Further reading",
                "; ".join(
                    self._render(item["url"], context)
                    for item in threat["further_reading"]
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
                    matched_signals=list(match.matched_signal_keys),
                    unmatched_signals=list(match.unmatched_signal_keys),
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
            "final_score": rca_case.final_score,
            "severity": rca_case.severity,
            "deviation_score": rca_case.component_scores.get("deviation", ""),
            "drift_score": rca_case.component_scores.get("drift", ""),
            "similarity_score": rca_case.component_scores.get("similarity", ""),
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
        details = []
        details.append(
            f"final_score={rca_case.final_score}; severity={rca_case.severity}; "
            f"confidence={rca_case.confidence}"
        )
        for key in candidate.supporting_evidence_keys:
            if key == "component_scores":
                scores = ", ".join(
                    f"{name}={value:.2f}" for name, value in rca_case.component_scores.items()
                )
                details.append(f"component_scores: {scores or 'none recorded'}")
            elif key == "changed_features":
                details.append(
                    "changed_features: " + (", ".join(rca_case.changed_features) or "none")
                )
            elif key == "behavioral_deviation":
                details.append(f"behavioral_deviation={rca_case.behavioral_deviation}")
            elif key == "drift_evidence":
                details.append(f"drift_evidence={rca_case.drift_evidence}")
            elif key == "similar_episodes":
                details.append(f"similar_episodes={rca_case.similar_episodes}")
            elif key == "related_incidents":
                details.append(f"related_incidents={rca_case.related_incidents}")
        return "; ".join(details)


__all__ = ["ExplanationBuilder"]
