"""Minimal structured audit logging used by the Phase 3 security hardening pass."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class AuditLogger:
    """Record an auditable security or tenant action."""

    def __init__(self, sink: list[dict[str, Any]] | None = None):
        self._sink = sink if sink is not None else []

    def record(
        self,
        actor_user_id: str,
        tenant_id: str,
        action: str,
        target: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "audit_event_id": f"audit-{datetime.now(timezone.utc).timestamp():.0f}-{actor_user_id}",
            "actor_user_id": actor_user_id,
            "tenant_id": tenant_id,
            "action": action,
            "target": target,
            "details": details or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._sink.append(event)
        logger.info(
            "audit_event actor=%s tenant=%s action=%s target=%s",
            actor_user_id,
            tenant_id,
            action,
            target,
        )
        return event


__all__ = ["AuditLogger"]
