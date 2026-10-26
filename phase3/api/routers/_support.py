"""Shared Phase 3 demo services, persistence, and tenant authorization."""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import jwt
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
from phase3.identity.auth_service import AuthService
from phase3.identity.membership_validator import MembershipValidator
from phase3.identity.sql_user_repository import SqlUserRepository
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
from phase3.rca.types import CandidateCause, RCACase
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
hypothesis_engine = HypothesisEngine(threat_matcher=threat_signature_matcher)
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


# ---------------------------------------------------------------------------
# Session identity
# ---------------------------------------------------------------------------
# Every tenant-scoped route derives the caller from a signed JWT
# ("Authorization: Bearer <token>") issued by POST /auth/login or
# POST /auth/register. The X-User-Id header is no longer trusted on its own;
# when it is sent alongside a token it must name the same user.
#
# CAPSTONE_AUTH_REQUIRED=false restores the legacy header-only identity. It
# exists so the older route tests (which predate login) keep working; do not
# use it for a shared or deployed instance.

LEGACY_DEMO_USER_ID = "demo-user"
_PLACEHOLDER_SECRETS = {"", "replace-with-random-32-byte-secret"}
_DEV_SECRET_PATH = Path(__file__).resolve().parents[3] / ".capstone_dev_jwt_secret"
_auth_service: Optional[AuthService] = None


def auth_required() -> bool:
    flag = os.getenv("CAPSTONE_AUTH_REQUIRED", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _resolve_jwt_secret() -> str:
    configured = os.getenv("PLATFORM_JWT_SECRET", "").strip()
    if configured not in _PLACEHOLDER_SECRETS:
        return configured
    try:
        existing = _DEV_SECRET_PATH.read_text(encoding="utf-8").strip()
        if len(existing.encode("utf-8")) >= 32:
            return existing
    except OSError:
        pass
    generated = secrets.token_urlsafe(48)
    try:
        _DEV_SECRET_PATH.write_text(generated, encoding="utf-8")
        print(
            "[auth] PLATFORM_JWT_SECRET is not set; generated a local development "
            f"secret at {_DEV_SECRET_PATH}. Set PLATFORM_JWT_SECRET for shared use."
        )
    except OSError:
        print(
            "[auth] PLATFORM_JWT_SECRET is not set and the development secret could "
            "not be saved; sessions will end when the API restarts."
        )
    return generated


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        try:
            _auth_service = AuthService(
                SqlUserRepository(lambda: platform_session_factory),
                {
                    "jwt_secret": _resolve_jwt_secret(),
                    "jwt_ttl_seconds": int(os.getenv("PLATFORM_JWT_TTL_SECONDS", "28800")),
                    "bcrypt_rounds": int(os.getenv("PLATFORM_BCRYPT_ROUNDS", "12")),
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=f"Auth misconfigured: {exc}") from exc
    return _auth_service


def reset_auth_service() -> None:
    """Drop the cached service (tests change secrets or databases between cases)."""
    global _auth_service
    _auth_service = None


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def user_id_from_token(token: str) -> str:
    try:
        claims = get_auth_service().verify_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=401,
            detail="Session expired; sign in again",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user_id = str(claims.get("sub") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    with platform_session_factory.session_scope() as session:
        if session.get(UserRow, user_id) is None:
            raise HTTPException(status_code=401, detail="Account no longer exists")
    return user_id


def resolve_request_user(authorization: Optional[str], x_user_id: Optional[str]) -> str:
    """Return the caller's user id from the bearer token (or legacy header)."""
    token = _bearer_token(authorization)
    if token:
        try:
            user_id = user_id_from_token(token)
        except HTTPException:
            if auth_required() or not x_user_id:
                raise
            return x_user_id
        if x_user_id and x_user_id != user_id:
            raise HTTPException(
                status_code=403, detail="X-User-Id does not match the signed-in user"
            )
        return user_id
    if not auth_required():
        if x_user_id:
            return x_user_id
        raise HTTPException(status_code=403, detail="Missing X-User-Id header")
    raise HTTPException(
        status_code=401,
        detail="Sign in required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user_id(
    authorization: Optional[str] = Header(None),
    user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> str:
    return resolve_request_user(authorization, user_id)


def _authorize_membership(
    tenant_id: Optional[str],
    authorization: Optional[str],
    user_id: Optional[str],
    required_role: Optional[Role] = None,
) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-Id header")
    resolved_user = resolve_request_user(authorization, user_id)
    middleware = TenantIsolationMiddleware(MembershipValidator(_DatabaseMembershipReader()))
    request = SimpleNamespace(session={"user_id": resolved_user, "tenant_id": tenant_id})
    try:
        middleware.authorize(request, tenant_id=tenant_id, required_role=required_role)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return resolved_user


def require_tenant_membership(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None),
) -> bool:
    _authorize_membership(tenant_id, authorization, user_id)
    return True


def require_operator_membership(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None),
) -> str:
    return _authorize_membership(tenant_id, authorization, user_id, Role.OPERATOR)


def require_owner_membership(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None),
) -> str:
    return _authorize_membership(tenant_id, authorization, user_id, Role.OWNER)


def ensure_demo_tenants() -> None:
    """Create the synthetic demo tenants if they do not exist yet."""
    with platform_session_factory.session_scope() as session:
        for tenant_id in TENANT_CONNECTIONS:
            if session.get(TenantRow, tenant_id) is None:
                session.add(
                    TenantRow(tenant_id=tenant_id, name=tenant_id.title(), source_mode="synthetic")
                )


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


def record_channel_delivery(
    tenant_id: str, incident_id: str, delivery: Dict[str, Any]
) -> Dict[str, Any]:
    """Append an outbound channel result (email, Slack, ...) to the RCA record."""
    record = jsonable_encoder(
        {
            "channel": delivery.get("channel") or delivery.get("notify_method"),
            "status": delivery.get("status"),
            "success": bool(delivery.get("success", delivery.get("sent", False))),
            "detail": delivery.get("detail") or delivery.get("message"),
            "tenant_id": tenant_id,
            "endpoint_id": f"{tenant_id}-{str(delivery.get('channel', 'channel')).lower()}",
        }
    )
    with platform_session_factory.session_scope() as session:
        row = (
            session.query(RcaCaseRow)
            .filter_by(tenant_id=tenant_id, incident_id=incident_id)
            .one_or_none()
        )
        if row is not None and row.body:
            body = dict(row.body)
            body["notification_deliveries"] = [
                *list(body.get("notification_deliveries") or []),
                record,
            ]
            row.body = body
    return record


def refresh_case_hypotheses(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill signature-based RCA for incidents stored before it existed.

    If a stored case has no threat-signature candidate but its evidence now
    matches a signature with MEDIUM or HIGH confidence, that candidate is
    ranked in (replacing a bare UNKNOWN). Any other stored result is returned
    unchanged, and the stored record itself is never modified.
    """
    stored = list(case_data.get("candidate_causes") or [])
    if any(str(item.get("rule_id", "")).startswith("rca.threat_signature") for item in stored):
        return case_data
    try:
        typed = dict(case_data)
        typed["batch_ts"] = datetime.fromisoformat(str(typed["batch_ts"]).replace("Z", "+00:00"))
        typed["candidate_causes"] = [CandidateCause(**candidate) for candidate in stored]
        case = RCACase(**typed)
    except (KeyError, TypeError, ValueError):
        return case_data
    threat = hypothesis_engine.threat_candidate(case)
    if threat is None:
        return case_data
    case.candidate_causes = hypothesis_engine.rank(case.candidate_causes, threat)
    refreshed = dict(case_data)
    refreshed["candidate_causes"] = jsonable_encoder(
        [asdict(candidate) for candidate in case.candidate_causes]
    )
    refreshed["confidence"] = ConfidenceScorer.score_case(case)
    return refreshed


def case_for_tenant(tenant_id: Optional[str], incident_id: str) -> Dict[str, Any]:
    resolved_tenant = _tenant_header(tenant_id)
    case = rca_cases.get(resolved_tenant, {}).get(incident_id)
    if case is not None:
        return refresh_case_hypotheses(jsonable_encoder(asdict(case)))
    with platform_session_factory.session_scope() as session:
        row = (
            session.query(RcaCaseRow)
            .filter_by(tenant_id=resolved_tenant, incident_id=incident_id)
            .one_or_none()
        )
        if row is None or not row.body:
            raise HTTPException(status_code=404, detail="Incident not found")
        return refresh_case_hypotheses(row.body["case"])


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
