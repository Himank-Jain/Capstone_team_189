"""Phase 3 shared dataclasses for platform identity and tenancy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from shared.types import AlertPayload, Severity


class Role(str, Enum):
    OWNER = "OWNER"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class ResolutionType(str, Enum):
    FIXED = "FIXED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    EXPECTED_CHANGE = "EXPECTED_CHANGE"
    AUTO_RECOVERED = "AUTO_RECOVERED"


@dataclass
class ResolvedAlertPayload(AlertPayload):
    lifecycle_status: str = "RESOLVED"


@dataclass(frozen=True)
class IncidentResolution:
    resolution_type: ResolutionType
    resolution_note: str
    resolved_by: str
    resolved_at: datetime


@dataclass(frozen=True)
class IncidentLifecycleState:
    incident_id: str
    tenant_id: str
    entity_id: str
    status: IncidentStatus
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    resolution: Optional[IncidentResolution] = None
    regression_of: Optional[str] = None
    recovering: bool = False


@dataclass(frozen=True)
class User:
    user_id: str
    email: str
    password_hash: str
    created_at: datetime


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    name: str
    source_mode: str
    created_at: datetime


@dataclass(frozen=True)
class TenantMembership:
    user_id: str
    tenant_id: str
    role: Role


@dataclass
class NotificationEndpoint:
    endpoint_id: str
    tenant_id: str
    channel: str
    target: str
    enabled: bool = True
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


@dataclass
class NotificationPolicy:
    tenant_id: str
    min_severity: Optional["Severity"] = None
    allowed_channels: Optional[List[str]] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    quiet_hours_tz: Optional[str] = None
    max_retries: int = 2
    timeout_seconds: float = 5.0
    retry_backoff_seconds: float = 1.0


@dataclass
class NotificationDeliveryResult:
    endpoint_id: str
    channel: str
    tenant_id: str
    success: bool
    detail: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    idempotent: bool = False
    dispatched_at: Optional[datetime] = None
