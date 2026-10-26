"""Lifecycle side effects separated from incident persistence."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from phase3.shared.types import ResolutionType

logger = logging.getLogger(__name__)


class DedupResetPort(Protocol):
    def reset_entity(self, entity_id: str) -> None: ...


class CorrelationPort(Protocol):
    def remove_entity(self, tenant_id: str, entity_id: str) -> None: ...


class EntityRecoveryPort(Protocol):
    def freeze(self, tenant_id: str, entity_id: str) -> None: ...

    def resolve(
        self, tenant_id: str, entity_id: str, resolution_type: ResolutionType
    ) -> None: ...


class DriftCachePort(Protocol):
    def invalidate(self, tenant_id: str, entity_id: str) -> None: ...


class NotificationPort(Protocol):
    async def send_resolved(
        self, tenant_id: str, incident_id: str, entity_id: str
    ) -> None: ...


class AuditPort(Protocol):
    def record(
        self,
        tenant_id: str,
        incident_id: str,
        actor_user_id: str,
        action: str,
        details: dict[str, Any],
    ) -> None: ...


class IncidentResolutionService:
    """Apply injected effects for lifecycle changes; persistence remains a router concern."""

    def __init__(
        self,
        dedup: DedupResetPort,
        correlation: CorrelationPort,
        entity_recovery: EntityRecoveryPort,
        drift_cache: DriftCachePort,
        notification_dispatcher: NotificationPort,
        audit_logger: AuditPort,
        escalation_memory: Any,
    ) -> None:
        self._dedup = dedup
        self._correlation = correlation
        self._entity_recovery = entity_recovery
        self._drift_cache = drift_cache
        self._notification_dispatcher = notification_dispatcher
        self._audit_logger = audit_logger
        self._escalation_memory = escalation_memory

    def freeze(self, tenant_id: str, incident_id: str, entity_id: str) -> None:
        self._entity_recovery.freeze(tenant_id, entity_id)
        self._audit_logger.record(
            tenant_id, incident_id, "", "baseline_frozen", {"entity_id": entity_id}
        )

    async def resolve(
        self,
        tenant_id: str,
        incident_id: str,
        entity_id: str,
        actor_user_id: str,
        resolution_type: ResolutionType,
        incident_group_id: str | None = None,
    ) -> None:
        self._dedup.reset_entity(entity_id)
        if incident_group_id:
            self._escalation_memory.clear_group(incident_group_id)
        self._correlation.remove_entity(tenant_id, entity_id)
        self._drift_cache.invalidate(tenant_id, entity_id)
        self._entity_recovery.resolve(tenant_id, entity_id, resolution_type)
        self._audit_logger.record(
            tenant_id,
            incident_id,
            actor_user_id,
            "incident_resolved",
            {"resolution_type": resolution_type.value, "entity_id": entity_id},
        )
        try:
            await self._notification_dispatcher.send_resolved(
                tenant_id, incident_id, entity_id
            )
        except Exception:
            logger.exception(
                "Failed to dispatch resolved notification for incident %s", incident_id
            )

    def record_transition(
        self,
        tenant_id: str,
        incident_id: str,
        actor_user_id: str,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit_logger.record(
            tenant_id, incident_id, actor_user_id, action, details or {}
        )

    def reopen(
        self,
        tenant_id: str,
        incident_id: str,
        entity_id: str,
        actor_user_id: str,
    ) -> None:
        self._entity_recovery.freeze(tenant_id, entity_id)
        self.record_transition(
            tenant_id, incident_id, actor_user_id, "incident_reopened", {"entity_id": entity_id}
        )


class DriftWorkerCachePort:
    """Bridge lifecycle invalidation to P2-M8's Redis-backed drift cache."""

    def __init__(self, drift_worker: Any) -> None:
        self._drift_worker = drift_worker

    def invalidate(self, tenant_id: str, entity_id: str) -> None:
        self._drift_worker.invalidate_cached_drift(entity_id)


class EntityStoreRecoveryPort:
    """Bridge incident resolution to P2-M4's additive baseline-writer hooks."""

    def __init__(
        self,
        entity_store_writer: Any,
        adaptation_alpha: float,
        adaptation_window: int,
        adaptation_batches: int,
    ) -> None:
        self._writer = entity_store_writer
        self._adaptation_alpha = adaptation_alpha
        self._adaptation_window = adaptation_window
        self._adaptation_batches = adaptation_batches

    def freeze(self, tenant_id: str, entity_id: str) -> None:
        self._writer.set_baseline_frozen(entity_id, True, tenant_id)

    def resolve(
        self, tenant_id: str, entity_id: str, resolution_type: ResolutionType
    ) -> None:
        self._writer.resolve_frozen_baseline(
            entity_id,
            resolution_type.value,
            self._adaptation_alpha,
            self._adaptation_window,
            self._adaptation_batches,
            tenant_id,
        )
