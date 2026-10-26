"""Notification delivery query endpoints."""

import re
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from phase3.db.models import RcaCaseRow, UserRow

from ..alert_notifications import (
    SUPPORTED_CHANNELS,
    build_test_payload,
    channel_statuses,
    clear_workspace_email_settings,
    email_settings_summary,
    save_workspace_email_settings,
    send_alert_notification,
)
from . import _support
from ._support import (
    require_operator_membership,
    require_owner_membership,
    require_tenant_membership,
)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(
    tags=["phase3-demo"],
    dependencies=[Depends(require_tenant_membership)],
)


@router.get("/notification-deliveries")
def list_notification_deliveries(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> list[Dict[str, Any]]:
    resolved_tenant = _support._tenant_header(tenant_id)
    with _support.platform_session_factory.session_scope() as session:
        rows = session.query(RcaCaseRow).filter_by(tenant_id=resolved_tenant).all()
        return [
            delivery
            for row in rows
            if row.body
            for delivery in row.body.get("notification_deliveries", [])
        ]


class NotificationTestRequest(BaseModel):
    channel: str


@router.get("/notifications/channels")
def list_notification_channels(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> list[Dict[str, str]]:
    return channel_statuses(_support._tenant_header(tenant_id))


@router.post("/notifications/test")
async def send_test_notification(
    payload: NotificationTestRequest,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    actor_user_id: str = Depends(require_operator_membership),
) -> Dict[str, Any]:
    resolved_tenant = _support._tenant_header(tenant_id)
    channel = payload.channel.strip().upper()
    if channel not in SUPPORTED_CHANNELS:
        raise HTTPException(status_code=422, detail=f"Unsupported channel: {payload.channel}")
    with _support.platform_session_factory.session_scope() as session:
        actor = session.get(UserRow, actor_user_id)
        actor_email = actor.email if actor is not None else actor_user_id
    return await send_alert_notification(
        channel,
        build_test_payload(resolved_tenant, actor_email),
        resolved_tenant,
        subject="[TEST] CAPSTONE-189 notification channel check",
        # A test email goes only to the person who asked for it.
        email_recipients=[actor_email] if "@" in actor_email else None,
    )


class EmailSettingsRequest(BaseModel):
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(587, ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"] = "starttls"
    username: str = Field(..., min_length=1, max_length=255)
    password: Optional[str] = Field(None, max_length=255)
    sender: Optional[str] = Field(None, max_length=255)
    recipients: List[str] = Field(default_factory=list, max_length=50)


@router.get("/notifications/email-settings")
def get_email_settings(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> Dict[str, Any]:
    return email_settings_summary(_support._tenant_header(tenant_id))


@router.put("/notifications/email-settings")
def put_email_settings(
    payload: EmailSettingsRequest,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    _owner: str = Depends(require_owner_membership),
) -> Dict[str, Any]:
    resolved_tenant = _support._tenant_header(tenant_id)
    sender = (payload.sender or payload.username).strip()
    if not _EMAIL.match(sender):
        raise HTTPException(status_code=422, detail="The sender must be an email address")
    bad = [item for item in payload.recipients if item.strip() and not _EMAIL.match(item.strip())]
    if bad:
        raise HTTPException(status_code=422, detail=f"Not an email address: {', '.join(bad)}")
    try:
        save_workspace_email_settings(
            resolved_tenant,
            host=payload.host,
            port=payload.port,
            security=payload.security,
            username=payload.username,
            password=payload.password,
            sender=sender,
            recipients=payload.recipients,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return email_settings_summary(resolved_tenant)


@router.delete("/notifications/email-settings")
def delete_email_settings(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    _owner: str = Depends(require_owner_membership),
) -> Dict[str, Any]:
    resolved_tenant = _support._tenant_header(tenant_id)
    clear_workspace_email_settings(resolved_tenant)
    return email_settings_summary(resolved_tenant)


__all__ = ["router"]
