"""Cloud connection endpoints."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header

from ..alert_notifications import channel_statuses
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
        "notification_channels": channel_statuses(resolved_tenant),
    }


__all__ = ["router"]
