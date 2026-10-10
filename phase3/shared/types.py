"""Phase 3 shared dataclasses for platform identity and tenancy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class Role(str, Enum):
    OWNER = "OWNER"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


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
