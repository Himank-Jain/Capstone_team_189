"""Cloud connection endpoints."""

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header

from ._support import TENANT_CONNECTIONS, _tenant_header, require_tenant_membership

router = APIRouter(
    tags=["phase3-demo"],
    dependencies=[Depends(require_tenant_membership)],
)


@router.get("/connections")
def list_connections(
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
) -> Dict[str, Any]:
    resolved_tenant = _tenant_header(tenant_id)
    provider, region = TENANT_CONNECTIONS.get(resolved_tenant, ("unknown", "unknown"))
    email_status = (
        "ready" if os.getenv("DEMO_EMAIL_PASSWORD", "").strip() else "credentials_required"
    )
    return {
        "tenant_id": resolved_tenant,
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
            {
                "channel": "SMS",
                "status": "credentials_required",
                "detail": "SMS provider credentials",
            },
            {
                "channel": "WEBHOOK",
                "status": "credentials_required",
                "detail": "Endpoint URL and signing secret",
            },
            {
                "channel": "PAGERDUTY",
                "status": "credentials_required",
                "detail": "PagerDuty routing key",
            },
        ],
    }


__all__ = ["router"]
