"""Incident query endpoints."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from phase3.db.models import IncidentRow, RcaCaseRow
from phase3.shared.types import IncidentStatus, ResolutionType

from . import _support
from ._support import (
    case_for_tenant,
    get_incident_resolution_service,
    require_operator_membership,
    require_tenant_membership,
)

router = APIRouter(
    tags=["phase3-demo"],
    dependencies=[Depends(require_tenant_membership)],
)


class ResolveIncidentRequest(BaseModel):
    resolution_type: ResolutionType
    note: str = Field(default="", max_length=2000)


def _lifecycle_payload(row: IncidentRow) -> Dict[str, Any]:
    return {
        "incident_id": row.incident_id,
        "tenant_id": row.tenant_id,
        "entity_id": row.entity_id,
        "status": row.status,
        "acknowledged_at": row.acknowledged_at,
        "resolved_at": row.resolved_at,
        "resolved_by": row.resolved_by,
        "resolution_type": row.resolution_type,
        "resolution_note": row.resolution_note,
        "regression_of": row.regression_of,
        "recovering": bool((row.details or {}).get("recovering", False)),
    }


def _incident_or_404(session, tenant_id: str, incident_id: str) -> IncidentRow:
    row = session.query(IncidentRow).filter_by(
        tenant_id=tenant_id, incident_id=incident_id
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return row


@router.get("/incidents")
def list_incidents(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> list[Dict[str, Any]]:
    resolved_tenant = _support._tenant_header(tenant_id)
    with _support.platform_session_factory.session_scope() as session:
        rows = session.query(RcaCaseRow).filter_by(tenant_id=resolved_tenant).all()
        incidents = {
            row.incident_id: row
            for row in session.query(IncidentRow).filter_by(tenant_id=resolved_tenant).all()
        }
        result = []
        for row in rows:
            if not row.body or not row.body.get("case"):
                continue
            case = dict(row.body["case"])
            incident = incidents.get(row.incident_id)
            if incident is not None:
                case.update(
                    {
                        "lifecycle_status": str(incident.status).upper(),
                        "regression_of": incident.regression_of,
                        "recovering": bool((incident.details or {}).get("recovering", False)),
                    }
                )
            result.append(case)
        return result


@router.get("/incidents/{incident_id}")
def get_incident(
    incident_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> Dict[str, Any]:
    return case_for_tenant(tenant_id, incident_id)


@router.get("/incidents/{incident_id}/lifecycle")
def get_incident_lifecycle(
    incident_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> Dict[str, Any]:
    resolved_tenant = _support._tenant_header(tenant_id)
    with _support.platform_session_factory.session_scope() as session:
        return _lifecycle_payload(_incident_or_404(session, resolved_tenant, incident_id))


@router.post("/incidents/{incident_id}/acknowledge")
def acknowledge_incident(
    incident_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    actor_user_id: str = Depends(require_operator_membership),
) -> Dict[str, Any]:
    resolved_tenant = _support._tenant_header(tenant_id)
    service = get_incident_resolution_service()
    with _support.platform_session_factory.session_scope() as session:
        row = _incident_or_404(session, resolved_tenant, incident_id)
        if row.status.upper() == IncidentStatus.RESOLVED.value:
            raise HTTPException(status_code=409, detail="Resolved incidents cannot be acknowledged")
        if row.status.upper() == IncidentStatus.OPEN.value:
            row.status = IncidentStatus.ACKNOWLEDGED.value
            row.acknowledged_at = datetime.now(timezone.utc)
            result = _lifecycle_payload(row)
        else:
            return _lifecycle_payload(row)
        entity_id = row.entity_id
    service.freeze(resolved_tenant, incident_id, entity_id)
    service.record_transition(
        resolved_tenant,
        incident_id,
        actor_user_id,
        "incident_acknowledged",
        {"entity_id": entity_id},
    )
    return result


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    request: ResolveIncidentRequest,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    actor_user_id: str = Depends(require_operator_membership),
) -> Dict[str, Any]:
    resolved_tenant = _support._tenant_header(tenant_id)
    service = get_incident_resolution_service()
    with _support.platform_session_factory.session_scope() as session:
        row = _incident_or_404(session, resolved_tenant, incident_id)
        if row.status.upper() == IncidentStatus.RESOLVED.value:
            return _lifecycle_payload(row)
        now = datetime.now(timezone.utc)
        row.status = IncidentStatus.RESOLVED.value
        row.resolved_at = now
        row.resolved_by = actor_user_id
        row.resolution_type = request.resolution_type.value
        row.resolution_note = request.note
        details = dict(row.details or {})
        details["recovering"] = False
        row.details = details
        entity_id = row.entity_id
        incident_group_id = details.get("incident_group_id")
        result = _lifecycle_payload(row)
    await service.resolve(
        resolved_tenant,
        incident_id,
        entity_id,
        actor_user_id,
        request.resolution_type,
        incident_group_id,
    )
    return result


@router.post("/incidents/{incident_id}/reopen")
def reopen_incident(
    incident_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    actor_user_id: str = Depends(require_operator_membership),
) -> Dict[str, Any]:
    resolved_tenant = _support._tenant_header(tenant_id)
    service = get_incident_resolution_service()
    with _support.platform_session_factory.session_scope() as session:
        row = _incident_or_404(session, resolved_tenant, incident_id)
        if row.status.upper() != IncidentStatus.RESOLVED.value:
            raise HTTPException(status_code=409, detail="Only resolved incidents can be reopened")
        row.status = IncidentStatus.OPEN.value
        row.acknowledged_at = None
        row.resolved_at = None
        row.resolved_by = None
        row.resolution_type = None
        row.resolution_note = None
        entity_id = row.entity_id
        result = _lifecycle_payload(row)
    service.reopen(resolved_tenant, incident_id, entity_id, actor_user_id)
    return result


__all__ = ["router"]
