"""Tenant onboarding endpoints."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from phase3.db.models import TenantMembershipRow

from . import _support
from ._support import (
    ONBOARDING_STEPS,
    OnboardingStartRequest,
    OnboardingStepRequest,
    onboarding_service,
    require_tenant_membership,
)

router = APIRouter(
    tags=["phase3-demo"],
    dependencies=[Depends(require_tenant_membership)],
)


@router.get("/membership/role")
def get_membership_role(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> Dict[str, str]:
    resolved_tenant = _support._tenant_header(tenant_id)
    if not user_id:
        raise HTTPException(status_code=403, detail="Missing X-User-Id header")
    with _support.platform_session_factory.session_scope() as session:
        membership = (
            session.query(TenantMembershipRow)
            .filter_by(user_id=user_id, tenant_id=resolved_tenant)
            .one_or_none()
        )
        if membership is None:
            raise HTTPException(status_code=403, detail="Tenant membership required")
        return {"role": membership.role}


@router.post("/onboarding")
def start_onboarding(
    payload: OnboardingStartRequest,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> Dict[str, Any]:
    if payload.source_mode not in {"synthetic", "live"}:
        raise HTTPException(status_code=422, detail="source_mode must be synthetic or live")
    session = onboarding_service.start_onboarding(
        user_id or payload.user_id,
        payload.tenant_name,
        payload.source_mode,
    )
    _support._persist_onboarding(session, tenant_id=tenant_id or "")
    return session


@router.get("/onboarding/{session_id}")
def get_onboarding(
    session_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> Dict[str, Any]:
    return _support._load_onboarding(session_id, tenant_id=tenant_id or "")


@router.post("/onboarding/{session_id}/steps/{step_name}")
def advance_onboarding(
    session_id: str,
    step_name: str,
    payload: OnboardingStepRequest,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> Dict[str, Any]:
    if step_name not in ONBOARDING_STEPS:
        raise HTTPException(status_code=404, detail="Unknown onboarding step")
    resolved_tenant = tenant_id or ""
    session = _support._load_onboarding(session_id, tenant_id=resolved_tenant)
    if (
        step_name == "enable_monitoring"
        and session["source_mode"] == "live"
        and not payload.confirm_live
    ):
        raise HTTPException(
            status_code=409,
            detail="Explicit confirmation is required to enable live monitoring",
        )
    if step_name == "enable_monitoring":
        session = onboarding_service.mark_complete(session_id, step_name, payload.payload)
    else:
        session = onboarding_service.record_step(session_id, step_name, payload.payload)
    _support._persist_onboarding(session, tenant_id=resolved_tenant)
    return session


__all__ = ["router"]
