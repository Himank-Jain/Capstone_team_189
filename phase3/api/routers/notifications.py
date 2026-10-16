"""Notification delivery query endpoints."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header

from phase3.db.models import RcaCaseRow

from . import _support
from ._support import require_tenant_membership

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


__all__ = ["router"]
