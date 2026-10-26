"""Root-cause analysis and explanation endpoints."""

from typing import Any, Dict, Optional
from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.encoders import jsonable_encoder

from phase3.db.models import IncidentRow, RcaCaseRow
from phase3.knowledge.explanation_builder import ExplanationBuilder
from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.recommendation_engine import RecommendationEngine
from phase3.rca.types import CandidateCause, RCACase

from . import _support
from ._support import case_for_tenant, process_demo_alert, require_tenant_membership

router = APIRouter(
    tags=["phase3-demo"],
    dependencies=[Depends(require_tenant_membership)],
)


def _rca_record(tenant_id: Optional[str], incident_id: str) -> Dict[str, Any]:
    resolved_tenant = _support._tenant_header(tenant_id)
    case_for_tenant(resolved_tenant, incident_id)
    with _support.platform_session_factory.session_scope() as session:
        row = (
            session.query(RcaCaseRow)
            .filter_by(tenant_id=resolved_tenant, incident_id=incident_id)
            .one_or_none()
        )
        if row is None or not row.body:
            raise HTTPException(status_code=404, detail="Incident not found")
        return {**row.body, "case": _support.refresh_case_hypotheses(row.body["case"])}


def _typed_case(record: Dict[str, Any]) -> RCACase:
    case_data = dict(record["case"])
    case_data["batch_ts"] = datetime.fromisoformat(
        str(case_data["batch_ts"]).replace("Z", "+00:00")
    )
    case_data["candidate_causes"] = [
        CandidateCause(**candidate)
        for candidate in case_data.get("candidate_causes", [])
    ]
    return RCACase(**case_data)


def _render_explanation(record: Dict[str, Any]) -> Dict[str, Any]:
    explanation = _support.explanation_builder.build(_typed_case(record))
    return jsonable_encoder(asdict(explanation))


def _render_recommendations(record: Dict[str, Any]) -> list[Dict[str, Any]]:
    recommendations = _support.recommendation_engine.recommend(_typed_case(record))
    return jsonable_encoder([asdict(check) for check in recommendations])


def _threat_checks(
    case: RCACase, threat: Dict[str, Any], loader: KnowledgeLoader
) -> list[Dict[str, Any]]:
    context = ExplanationBuilder._template_context(case)
    return [
        {
            "check": loader.template_value(item["check"], context),
            "why": loader.template_value(item["why"], context),
            "expected_result": loader.template_value(item["expected_result"], context),
            "risk": str(item["risk"]),
        }
        for item in threat["investigative_checks"]
    ]


@router.get("/incidents/{incident_id}/investigation")
def get_incident_investigation(
    incident_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> Dict[str, Any]:
    record = _rca_record(tenant_id, incident_id)
    return {
        "case": record["case"],
        "explanation": _render_explanation(record),
        "recommendations": _render_recommendations(record),
        "notification_deliveries": record.get("notification_deliveries", []),
    }


@router.get("/incidents/{incident_id}/explanation")
def get_incident_explanation(
    incident_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> Any:
    return _render_explanation(_rca_record(tenant_id, incident_id))


@router.get("/incidents/{incident_id}/recommendations")
def get_incident_recommendations(
    incident_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> list[Dict[str, Any]]:
    return _render_recommendations(_rca_record(tenant_id, incident_id))


@router.get("/incidents/{incident_id}/mitigation")
def get_incident_mitigation(
    incident_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> Dict[str, Any]:
    resolved_tenant = _support._tenant_header(tenant_id)
    record = _rca_record(resolved_tenant, incident_id)
    case = _typed_case(record)
    loader = _support.knowledge_loader
    matcher = _support.threat_signature_matcher
    matches = matcher.match(case)
    eligible_match = next(
        (
            match
            for match in matches
            if match.match_confidence in {"MEDIUM", "HIGH"}
            and loader.retrieve_threat_entry(match.threat_id) is not None
        ),
        None,
    )
    provider_key = case.cloud_provider.casefold()
    if eligible_match is None:
        checks = RecommendationEngine(loader, matcher).recommend(case)
        mitigation = {"immediate": [], "short_term": [], "hardening": []}
        mitre_attack = []
        resolution_criteria = []
        threat_summary = None
        mitigation_mode = "generic"
    else:
        threat = loader.retrieve_threat_entry(eligible_match.threat_id)
        if threat is None:
            raise RuntimeError(
                f"validated threat entry disappeared: {eligible_match.threat_id}"
            )
        checks = _threat_checks(case, threat, loader)
        context = ExplanationBuilder._template_context(case)
        mitigation = {}
        for phase in ("immediate", "short_term", "hardening"):
            mitigation[phase] = []
            for step in threat["mitigation"][phase]:
                provider_text = step.get(provider_key)
                text = provider_text or step["generic"]
                mitigation[phase].append(
                    {
                        "text": loader.template_value(text, context),
                        "provider_specific": bool(provider_text),
                    }
                )
        checks = RecommendationEngine(loader, matcher).recommend(case)
        mitre_attack = threat["mitre_attack"]
        resolution_criteria = [
            loader.template_value(item, context)
            for item in threat["resolution_criteria"]
        ]
        threat_summary = {
            "threat_id": loader.public_threat_id(eligible_match.threat_id),
            "title": threat["title"],
            "match_confidence": eligible_match.match_confidence,
        }
        mitigation_mode = "threat_specific"

    with _support.platform_session_factory.session_scope() as session:
        incident = (
            session.query(IncidentRow)
            .filter_by(tenant_id=resolved_tenant, incident_id=incident_id)
            .one_or_none()
        )
        incident_status = str(incident.status).casefold() if incident else ""
        incident_details = (incident.details or {}) if incident else {}
    is_resolved = incident_status.upper() == "RESOLVED"
    response: Dict[str, Any] = {
        "incident_id": incident_id,
        "rca_case_id": case.rca_case_id,
        "cloud_provider": case.cloud_provider,
        "threat": threat_summary,
        "match_basis": ExplanationBuilder._match_basis(matches),
        "mitigation_mode": mitigation_mode,
        "is_retrospective": is_resolved,
        "mitigation": mitigation,
        "mitre_attack": mitre_attack,
        "investigative_checks": jsonable_encoder(checks),
        "resolution_criteria": resolution_criteria,
    }
    if is_resolved:
        stored_resolution = incident_details.get("resolution_record")
        if not isinstance(stored_resolution, dict):
            stored_resolution = incident_details
        resolution_record = {
            "type": stored_resolution.get("type")
            or stored_resolution.get("resolution_type"),
            "who": stored_resolution.get("who")
            or stored_resolution.get("resolved_by")
            or stored_resolution.get("resolved_by_user_id")
            or stored_resolution.get("actor_user_id"),
            "when": stored_resolution.get("when")
            or stored_resolution.get("resolved_at")
            or stored_resolution.get("timestamp"),
            "note": stored_resolution.get("note"),
        }
        response["post_incident_review"] = {
            "promoted_phase": "hardening",
            "hardening": mitigation["hardening"],
            "resolution_record": resolution_record,
        }
    return response


__all__ = ["process_demo_alert", "router"]
