"""Shared Phase 3 demo services, persistence, and tenant authorization."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from phase3.db.models import (
    AuditEventRow,
    Base,
    IncidentRow,
    RcaCaseRow,
    TenantMembershipRow,
    TenantRow,
    UserRow,
)
from phase3.db.session import PlatformSessionFactory
from phase3.identity.membership_validator import MembershipValidator
from phase3.knowledge.explanation_builder import ExplanationBuilder
from phase3.knowledge.knowledge_loader import KnowledgeLoader
from phase3.knowledge.recommendation_engine import RecommendationEngine
from phase3.knowledge.threat_signature_matcher import ThreatSignatureMatcher
from phase3.notifications.notification_dispatcher import (
    InMemoryNotificationDeliveryRecorder,
    NotificationDispatcher,
)
from phase3.onboarding.wizard_service import OnboardingWizardService
from phase3.rca.confidence_scorer import ConfidenceScorer
from phase3.rca.evidence_builder import EvidenceBuilder
from phase3.rca.hypothesis_engine import HypothesisEngine
from phase3.rca.types import RCACase
from phase3.security.middleware import TenantIsolationMiddleware
from phase3.lifecycle.incident_resolution_service import IncidentResolutionService
from phase3.shared.types import (
    NotificationEndpoint,
    NotificationPolicy,
    ResolvedAlertPayload,
    Role,
    TenantMembership,
)
from shared.types import (
    AlertPayload,
    GroupType,
    NotifyMethod,
    Severity,
    SevLevel,
)

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
    "acme": ("AWS", "us-west-2"),
}

onboarding_service = OnboardingWizardService()
onboarding_tenant_ids: Dict[str, str] = {}
knowledge_loader = KnowledgeLoader()
threat_signature_matcher = ThreatSignatureMatcher()
evidence_builder = EvidenceBuilder()
hypothesis_engine = HypothesisEngine()
explanation_builder = ExplanationBuilder(knowledge_loader, threat_signature_matcher)
recommendation_engine = RecommendationEngine(knowledge_loader, threat_signature_matcher)
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
        if getattr(payload, "lifecycle_status", None) == "RESOLVED":
            return {"success": True, "detail": f"Incident {payload.alert_id} resolved"}
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


class _DatabaseMembershipReader:
    def fetch_membership(self, user_id: str, tenant_id: str) -> TenantMembership | None:
        with platform_session_factory.session_scope() as session:
            row = (
                session.query(TenantMembershipRow)
                .filter_by(user_id=user_id, tenant_id=tenant_id)
                .one_or_none()
            )
            if row is None:
                return None
            return TenantMembership(
                user_id=row.user_id,
                tenant_id=row.tenant_id,
                role=Role(row.role),
            )


def require_tenant_membership(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> bool:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-Id header")
    if not user_id:
        raise HTTPException(status_code=403, detail="Missing X-User-Id header")

    middleware = TenantIsolationMiddleware(MembershipValidator(_DatabaseMembershipReader()))
    request = SimpleNamespace(session={"user_id": user_id, "tenant_id": tenant_id})
    try:
        middleware.authorize(request, tenant_id=tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return True


def require_operator_membership(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-Id header")
    if not user_id:
        raise HTTPException(status_code=403, detail="Missing X-User-Id header")

    middleware = TenantIsolationMiddleware(MembershipValidator(_DatabaseMembershipReader()))
    request = SimpleNamespace(session={"user_id": user_id, "tenant_id": tenant_id})
    try:
        middleware.authorize(request, tenant_id=tenant_id, required_role=Role.OPERATOR)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return user_id


class DatabaseAuditPort:
    def record(
        self,
        tenant_id: str,
        incident_id: str,
        actor_user_id: str,
        action: str,
        details: Dict[str, Any],
    ) -> None:
        with platform_session_factory.session_scope() as session:
            session.add(
                AuditEventRow(
                    audit_event_id=str(uuid.uuid4()),
                    actor_user_id=actor_user_id or "system",
                    tenant_id=tenant_id,
                    action=action,
                    target=incident_id,
                    details=details,
                )
            )


_incident_resolution_service: Optional[IncidentResolutionService] = None


def configure_incident_resolution_service(service: IncidentResolutionService) -> None:
    global _incident_resolution_service
    _incident_resolution_service = service


def get_incident_resolution_service() -> IncidentResolutionService:
    if _incident_resolution_service is None:
        raise HTTPException(status_code=503, detail="Incident lifecycle service is unavailable")
    return _incident_resolution_service


async def send_resolved_notification(
    tenant_id: str, incident_id: str, entity_id: str
) -> None:
    with platform_session_factory.session_scope() as session:
        row = session.query(IncidentRow).filter_by(
            tenant_id=tenant_id, incident_id=incident_id
        ).one_or_none()
        alert_data = (row.details or {}).get("alert_payload") if row is not None else None
    if not alert_data:
        return
    alert = _typed_alert(alert_data)
    policy = NotificationPolicy(tenant_id=tenant_id, allowed_channels=["page", "slack", "email"])
    await _notification_dispatcher.dispatch(
        ResolvedAlertPayload(**vars(alert)), policy, idempotency_suffix="resolved"
    )


def provision_demo_identity() -> str:
    """Create the explicitly demo-only principal and its tenant memberships."""
    user_id = "demo-user"
    with platform_session_factory.session_scope() as session:
        if session.get(UserRow, user_id) is None:
            session.add(
                UserRow(
                    user_id=user_id,
                    email="demo@capstone189.local",
                    password_hash="demo-only",
                )
            )
            session.flush()
        for tenant_id in TENANT_CONNECTIONS:
            if session.get(TenantRow, tenant_id) is None:
                session.add(
                    TenantRow(
                        tenant_id=tenant_id,
                        name=tenant_id.title(),
                        source_mode="synthetic",
                    )
                )
                session.flush()
            membership = (
                session.query(TenantMembershipRow)
                .filter_by(user_id=user_id, tenant_id=tenant_id)
                .one_or_none()
            )
            if membership is None:
                session.add(
                    TenantMembershipRow(
                        membership_id=f"demo-membership-{tenant_id}",
                        user_id=user_id,
                        tenant_id=tenant_id,
                        role="OWNER",
                    )
                )
    return user_id


def _tenant_header(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-Id header")
    return tenant_id


def _onboarding_row_id(session_id: str, tenant_id: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{session_id}".encode("utf-8")).hexdigest()[:32]
    return f"onb-{digest}"


def _persist_onboarding(session_data: Dict[str, Any], tenant_id: str) -> None:
    row_id = _onboarding_row_id(str(session_data["session_id"]), tenant_id)
    with platform_session_factory.session_scope() as session:
        row = session.get(TenantRow, row_id)
        if row is None:
            row = TenantRow(
                tenant_id=row_id,
                name=str(session_data["tenant_name"]),
                source_mode=str(session_data["source_mode"]),
                onboarding_state=jsonable_encoder(session_data),
            )
            session.add(row)
        else:
            row.onboarding_state = jsonable_encoder(session_data)
    onboarding_tenant_ids[str(session_data["session_id"])] = tenant_id


def _load_onboarding(session_id: str, tenant_id: str) -> Dict[str, Any]:
    if onboarding_tenant_ids.get(session_id) not in (None, tenant_id):
        raise HTTPException(status_code=404, detail="Onboarding session not found")
    with platform_session_factory.session_scope() as session:
        row = session.get(TenantRow, _onboarding_row_id(session_id, tenant_id))
        if row is None or not row.onboarding_state:
            raise HTTPException(status_code=404, detail="Onboarding session not found")
    try:
        session_data = onboarding_service.get_session(session_id)
    except KeyError:
        session_data = onboarding_service.restore_session(row.onboarding_state)
    onboarding_tenant_ids[session_id] = tenant_id
    return session_data


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


def case_for_tenant(tenant_id: Optional[str], incident_id: str) -> Dict[str, Any]:
    resolved_tenant = _tenant_header(tenant_id)
    case = rca_cases.get(resolved_tenant, {}).get(incident_id)
    if case is not None:
        return jsonable_encoder(asdict(case))
    with platform_session_factory.session_scope() as session:
        row = (
            session.query(RcaCaseRow)
            .filter_by(tenant_id=resolved_tenant, incident_id=incident_id)
            .one_or_none()
        )
        if row is None or not row.body:
            raise HTTPException(status_code=404, detail="Incident not found")
        return row.body["case"]


async def process_demo_alert(
    payload: Dict[str, Any],
    tenant_id: str,
    case_evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build RCA/KB results and record the demo notification for one alert."""
    alert = _typed_alert(payload)
    default_provider, default_region = TENANT_CONNECTIONS.get(
        tenant_id, ("unknown", "unknown")
    )
    provider = str(payload.get("cloud_provider") or default_provider)
    region = str(payload.get("region") or default_region)
    case = evidence_builder.build(
        alert,
        tenant_id=tenant_id,
        incident_id=alert.alert_id,
        cloud_provider=provider,
        region=region,
    )
    case.changed_features = [
        str(feature) for feature in payload.get("contributing_features", [])
    ] or case.changed_features
    case.observed_window.update(case_evidence or {})
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
        incident = (
            session.query(IncidentRow)
            .filter_by(tenant_id=tenant_id, incident_id=alert.alert_id)
            .one_or_none()
        )
        incident_details = {
            "alert_payload": jsonable_encoder(payload),
            "incident_group_id": payload.get("incident_group_id"),
            "recovery_streak": 0,
            "recovering": False,
        }
        if incident is None:
            incident = IncidentRow(
                incident_id=alert.alert_id,
                tenant_id=tenant_id,
                entity_id=alert.entity_id,
                severity=alert.severity.value,
                status="OPEN",
                first_seen_at=alert.batch_ts,
                last_seen_at=alert.batch_ts,
                details=incident_details,
                regression_of=payload.get("regression_of"),
            )
            session.add(incident)
            session.flush()
            session.add(
                AuditEventRow(
                    audit_event_id=str(uuid.uuid4()),
                    actor_user_id="system",
                    tenant_id=tenant_id,
                    action="incident_opened",
                    target=alert.alert_id,
                    details={"entity_id": alert.entity_id},
                )
            )
        else:
            incident.last_seen_at = alert.batch_ts
            incident.severity = alert.severity.value
            previous_details = dict(incident.details or {})
            previous_details.update(
                {
                    "alert_payload": incident_details["alert_payload"],
                    "incident_group_id": incident_details["incident_group_id"],
                }
            )
            incident.details = previous_details
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
        "explanation": asdict(explanation),
        "recommendations": [asdict(check) for check in recommendations],
    }
