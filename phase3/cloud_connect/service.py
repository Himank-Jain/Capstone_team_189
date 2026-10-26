"""Thin cloud-connection layer used by onboarding and platform setup."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ResourceSummary:
    resource_id: str
    resource_type: str
    resource_name: str
    provider: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CloudConnection:
    connection_id: str
    tenant_id: str
    provider: str
    credentials_cfg: dict[str, Any] | None = None
    dry_run: bool = True
    status: str = "pending"
    last_validated_at: datetime | None = None
    created_at: datetime | None = None
    credentials: dict[str, Any] | None = None

    def __post_init__(self):
        if self.credentials_cfg is None and self.credentials is not None:
            self.credentials_cfg = self.credentials
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


class ResourceDiscoveryService:
    """Discover resources from a cloud connection by delegating to the connector."""

    def __init__(self, cloud_connection_service: CloudConnectionService | None = None):
        self._cloud_connection_service = cloud_connection_service or CloudConnectionService()

    def discover(
        self, connection: CloudConnection, connector: Any | None = None
    ) -> list[ResourceSummary]:
        return self._cloud_connection_service.list_resources(connection, connector)


class CloudConnectionService:
    """Store credentials and validate a provider connection without owning provider SDK logic."""

    def __init__(self, credential_store: Any | None = None):
        self._credential_store = credential_store

    def save_connection(self, connection: CloudConnection) -> CloudConnection:
        cfg = dict(connection.credentials_cfg or connection.credentials or {})
        connection.credentials_cfg = cfg
        if self._credential_store is not None and cfg:
            self._credential_store.save(connection.tenant_id, connection.provider, cfg)
        connection.status = "registered"
        return connection

    def validate_connection(
        self, connection: CloudConnection, connector: Any | None = None
    ) -> bool:
        if connector is None:
            connection.status = "validated"
            connection.last_validated_at = datetime.now(timezone.utc)
            return True
        ok = bool(connector.health_check())
        connection.status = "validated" if ok else "validation_failed"
        if ok:
            connection.last_validated_at = datetime.now(timezone.utc)
        return ok

    def list_resources(
        self, connection: CloudConnection, connector: Any | None = None
    ) -> list[ResourceSummary]:
        if connector is None:
            return []
        raw_items = connector.list_resources() if hasattr(connector, "list_resources") else []
        summary: list[ResourceSummary] = []
        for raw in raw_items:
            if isinstance(raw, ResourceSummary):
                summary.append(raw)
                continue
            if not isinstance(raw, dict):
                continue
            summary.append(
                ResourceSummary(
                    resource_id=str(raw.get("resource_id") or raw.get("id") or "unknown"),
                    resource_type=str(raw.get("resource_type") or raw.get("type") or "unknown"),
                    resource_name=str(raw.get("resource_name") or raw.get("name") or "unknown"),
                    provider=connection.provider,
                    metadata={
                        k: v
                        for k, v in raw.items()
                        if k
                        not in {
                            "resource_id",
                            "id",
                            "resource_type",
                            "type",
                            "resource_name",
                            "name",
                        }
                    },
                )
            )
        return summary


__all__ = [
    "CloudConnection",
    "CloudConnectionService",
    "ResourceDiscoveryService",
    "ResourceSummary",
]
