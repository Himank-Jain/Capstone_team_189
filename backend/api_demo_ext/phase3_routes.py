"""Phase 3 API adapters for the local synthetic demo."""

from __future__ import annotations

import os
import hashlib
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from phase3.db.models import Base, RcaCaseRow, TenantRow
from phase3.db.session import PlatformSessionFactory
from phase3.knowledge.explanation_builder import ExplanationBuilder
from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.recommendation_engine import RecommendationEngine
from phase3.notifications.notification_dispatcher import (
    InMemoryNotificationDeliveryRecorder,
    NotificationDispatcher,
)
from phase3.onboarding.wizard_service import OnboardingWizardService
from phase3.rca.confidence_scorer import ConfidenceScorer
from phase3.rca.evidence_builder import EvidenceBuilder
from phase3.rca.hypothesis_engine import HypothesisEngine
from phase3.rca.types import RCACase
from phase3.shared.types import NotificationEndpoint, NotificationPolicy
from shared.types import (
    AlertPayload,
    GroupType,
    NotifyMethod,
    SevLevel,
    Severity,
)

router = APIRouter(tags=["phase3-demo"])

ONBOARDING_STEPS = (
    "tenant",
    "cloud_connection",
    "credential_validation",
    "resource_discovery",
    "notification_setup",
    "test_notification",
    "enable_monitoring",
)

TENANT_CONNECTIONS = {
    "google": ("GCP", "us-central1"),
    "microsoft": ("Azure", "eastus"),
    "amazon": ("AWS", "us-east-1"),
    "oracle": ("OCI", "us-phoenix-1"),
    "openai": ("AWS", "us-west-2"),
}

onboarding_service = OnboardingWizardService()
knowledge_loader = KnowledgeLoader()
evidence_builder = EvidenceBuilder()
hypothesis_engine = HypothesisEngine()
explanation_builder = ExplanationBuilder(knowledge_loader)
recommendation_engine = RecommendationEngine(knowledge_loader)
rca_cases: Dict[str, Dict[str, RCACase]] = {}
rca_explanations: Dict[str, Dict[str, Any]] = {}
rca_recommendations: Dict[str, Dict[str, Any]] = {}
platform_session_factory = PlatformSessionFactory(
    {
        "database_url": os.getenv(
            "CAPSTONE_DATABASE_URL",
            "sqlite:///./capstone_phase3_demo.db",
        )
    }
)
Base.metadata.create_all(platform_session_factory.build_engine())


class OnboardingStartRequest(BaseModel):
    user_id: str = "demo-user"
    tenant_name: str
    source_mode: str = "synthetic"


class OnboardingStepRequest(BaseModel):
    payload: Dict[str, Any] = {}
    confirm_live: bool = False


class _DashboardNotifier:
    channel_name = "page"

    async def notify(self, payload: AlertPayload) -> Dict[str, Any]:
        return {"success": True, "detail": f"Alert {payload.alert_id} displayed on dashboard"}


_delivery_recorder = InMemoryNotificationDeliveryRecorder()
_notification_dispatcher = NotificationDispatcher(
    notifiers=[_DashboardNotifier()],
    endpoints=[
        NotificationEndpoint(
            endpoint_id=f"{tenant_id}-dashboard",
            tenant_id=tenant_id,
            channel="PAGE",
            target=f"dashboard://{tenant_id}/alerts",
        )
        for tenant_id in TENANT_CONNECTIONS
    ],
    delivery_recorder=_delivery_recorder,
)


def _tenant_header(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-Id header")
    return tenant_id


def _onboarding_row_id(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return f"onb-{digest}"


def _persist_onboarding(session_data: Dict[str, Any]) -> None:
    tenant_id = _onboarding_row_id(str(session_data["session_id"]))
    with platform_session_factory.session_scope() as session:
        row = session.get(TenantRow, tenant_id)
        if row is None:
            row = TenantRow(
                tenant_id=tenant_id,
                name=str(session_data["tenant_name"]),
                source_mode=str(session_data["source_mode"]),
                onboarding_state=jsonable_encoder(session_data),
            )
            session.add(row)
        else:
            row.onboarding_state = jsonable_encoder(session_data)


def _load_onboarding(session_id: str) -> Dict[str, Any]:
    try:
        return onboarding_service.get_session(session_id)
    except KeyError:
        with platform_session_factory.session_scope() as session:
            row = session.get(TenantRow, _onboarding_row_id(session_id))
            if row is None or not row.onboarding_state:
                raise HTTPException(status_code=404, detail="Onboarding session not found")
            return onboarding_service.restore_session(row.onboarding_state)


def _typed_alert(payload: Dict[str, Any]) -> AlertPayload:
    timestamp = str(payload["batch_ts"])
    parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return AlertPayload(
        alert_id=str(payload["alert_id"]),
        entity_id=str(payload["entity_id"]),
        batch_ts=parsed_timestamp,
        final_score=float(payload["final_score"]),
        severity=Severity(str(payload["severity"])),
        sev_level=SevLevel(str(payload["sev_level"])),
        deviation_score=float(payload["deviation_score"]),
        drift_score=float(payload["drift_score"]),
        similarity_score=float(payload["similarity_score"]),
        similar_episodes=list(payload.get("similar_episodes") or []),
        related_ids=list(payload.get("related_ids") or []),
        group_type=GroupType(str(payload["group_type"])),
        target_team=str(payload.get("target_team") or "unassigned"),
        notify_method=NotifyMethod(str(payload.get("notify_method") or "PAGE")),
        cloud_provider=str(payload.get("cloud_provider") or "unknown"),
        region=str(payload.get("region") or "unknown"),
    )


async def process_demo_alert(payload: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """Build RCA/KB results and record the demo notification for one alert."""
    alert = _typed_alert(payload)
    provider, region = TENANT_CONNECTIONS.get(tenant_id, ("unknown", "unknown"))
    case = evidence_builder.build(
        alert,
        tenant_id=tenant_id,
        incident_id=alert.alert_id,
        cloud_provider=provider,
        region=region,
    )
    case.changed_features = [
        str(feature)
        for feature in payload.get("contributing_features", [])
    ] or case.changed_features
    case.candidate_causes = hypothesis_engine.generate(case)
    case.confidence = ConfidenceScorer.score_case(case)
    explanation = explanation_builder.build(case)
    recommendations = recommendation_engine.recommend(case)
    policy = NotificationPolicy(tenant_id=tenant_id, allowed_channels=["PAGE"])
    deliveries = await _notification_dispatcher.dispatch(alert, policy)
    record = {
        "case": jsonable_encoder(asdict(case)),
        "explanation": jsonable_encoder(asdict(explanation)),
        "recommendations": jsonable_encoder([asdict(check) for check in recommendations]),
        "notification_deliveries": jsonable_encoder([asdict(result) for result in deliveries]),
    }
    with platform_session_factory.session_scope() as session:
        tenant = session.get(TenantRow, tenant_id)
        if tenant is None:
            session.add(
                TenantRow(
                    tenant_id=tenant_id,
                    name=tenant_id.title(),
                    source_mode="synthetic",
                    onboarding_state=None,
                )
            )
            session.flush()
        row = session.get(RcaCaseRow, case.rca_case_id)
        if row is None:
            row = RcaCaseRow(
                rca_case_id=case.rca_case_id,
                incident_id=case.incident_id,
                tenant_id=tenant_id,
                title=explanation.headline,
                body=record,
            )
            session.add(row)
        else:
            row.title = explanation.headline
            row.body = record

    rca_cases.setdefault(tenant_id, {})[case.incident_id] = case
    rca_explanations.setdefault(tenant_id, {})[case.incident_id] = explanation
    rca_recommendations.setdefault(tenant_id, {})[case.incident_id] = recommendations
    return {
        "rca_case_id": case.rca_case_id,
        "candidate_causes": [asdict(candidate) for candidate in case.candidate_causes],
        "confidence": case.confidence,
        "notification_deliveries": [asdict(result) for result in deliveries],
    }


@router.post("/onboarding")
def start_onboarding(payload: OnboardingStartRequest) -> Dict[str, Any]:
    if payload.source_mode not in {"synthetic", "live"}:
        raise HTTPException(status_code=422, detail="source_mode must be synthetic or live")
    session = onboarding_service.start_onboarding(
        payload.user_id,
        payload.tenant_name,
        payload.source_mode,
    )
    _persist_onboarding(session)
    return session


@router.get("/onboarding/{session_id}")
def get_onboarding(session_id: str) -> Dict[str, Any]:
    return _load_onboarding(session_id)


@router.post("/onboarding/{session_id}/steps/{step_name}")
def advance_onboarding(
    session_id: str,
    step_name: str,
    payload: OnboardingStepRequest,
) -> Dict[str, Any]:
    if step_name not in ONBOARDING_STEPS:
        raise HTTPException(status_code=404, detail="Unknown onboarding step")
    session = _load_onboarding(session_id)
    if step_name == "enable_monitoring" and session["source_mode"] == "live" and not payload.confirm_live:
        raise HTTPException(status_code=409, detail="Explicit confirmation is required to enable live monitoring")
    if step_name == "enable_monitoring":
        session = onboarding_service.mark_complete(session_id, step_name, payload.payload)
    else:
        session = onboarding_service.record_step(session_id, step_name, payload.payload)
    _persist_onboarding(session)
    return session


@router.get("/connections")
def list_connections(tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id")) -> Dict[str, Any]:
    tenant_id = _tenant_header(tenant_id)
    provider, region = TENANT_CONNECTIONS.get(tenant_id, ("unknown", "unknown"))
    email_status = "ready" if os.getenv("DEMO_EMAIL_PASSWORD", "").strip() else "credentials_required"
    return {
        "tenant_id": tenant_id,
        "source_mode": "synthetic",
        "connections": [
            {
                "provider": provider,
                "region": region,
                "status": "synthetic",
                "dry_run": True,
            }
        ],
        "notification_channels": [
            {"channel": "PAGE", "status": "ready", "detail": "In-dashboard delivery"},
            {"channel": "EMAIL", "status": email_status, "detail": "Gmail SMTP"},
            {"channel": "SLACK", "status": "simulated", "detail": "Demo response only"},
            {"channel": "SMS", "status": "credentials_required", "detail": "SMS provider credentials"},
            {"channel": "WEBHOOK", "status": "credentials_required", "detail": "Endpoint URL and signing secret"},
            {"channel": "PAGERDUTY", "status": "credentials_required", "detail": "PagerDuty routing key"},
        ],
    }


def _case_for_tenant(tenant_id: Optional[str], incident_id: str) -> Dict[str, Any]:
    resolved_tenant = _tenant_header(tenant_id)
    case = rca_cases.get(resolved_tenant, {}).get(incident_id)
    if case is not None:
        return jsonable_encoder(asdict(case))
    with platform_session_factory.session_scope() as session:
        row = session.query(RcaCaseRow).filter_by(
            tenant_id=resolved_tenant,
            incident_id=incident_id,
        ).one_or_none()
        if row is None or not row.body:
            raise HTTPException(status_code=404, detail="Incident not found")
        case_data = row.body["case"]
    return case_data


@router.get("/incidents")
def list_incidents(tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id")) -> list[Dict[str, Any]]:
    tenant_id = _tenant_header(tenant_id)
    with platform_session_factory.session_scope() as session:
        rows = session.query(RcaCaseRow).filter_by(tenant_id=tenant_id).all()
        return [row.body["case"] for row in rows if row.body]


@router.get("/incidents/{incident_id}")
def get_incident(
    incident_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> Dict[str, Any]:
    return _case_for_tenant(tenant_id, incident_id)


@router.get("/incidents/{incident_id}/explanation")
def get_incident_explanation(
    incident_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> Any:
    resolved_tenant = _tenant_header(tenant_id)
    _case_for_tenant(resolved_tenant, incident_id)
    with platform_session_factory.session_scope() as session:
        row = session.query(RcaCaseRow).filter_by(
            tenant_id=resolved_tenant,
            incident_id=incident_id,
        ).one_or_none()
        if row is None or not row.body:
            raise HTTPException(status_code=404, detail="Incident not found")
        return row.body["explanation"]


@router.get("/incidents/{incident_id}/recommendations")
def get_incident_recommendations(
    incident_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> list[Dict[str, Any]]:
    resolved_tenant = _tenant_header(tenant_id)
    _case_for_tenant(resolved_tenant, incident_id)
    with platform_session_factory.session_scope() as session:
        row = session.query(RcaCaseRow).filter_by(
            tenant_id=resolved_tenant,
            incident_id=incident_id,
        ).one_or_none()
        if row is None or not row.body:
            raise HTTPException(status_code=404, detail="Incident not found")
        return row.body["recommendations"]


@router.get("/notification-deliveries")
def list_notification_deliveries(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> list[Dict[str, Any]]:
    resolved_tenant = _tenant_header(tenant_id)
    with platform_session_factory.session_scope() as session:
        rows = session.query(RcaCaseRow).filter_by(tenant_id=resolved_tenant).all()
        return [
            delivery
            for row in rows
            if row.body
            for delivery in row.body.get("notification_deliveries", [])
        ]


__all__ = ["process_demo_alert", "router"]
