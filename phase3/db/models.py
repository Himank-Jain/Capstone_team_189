"""SQLAlchemy models for the Phase 3 platform schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    memberships: Mapped[list["TenantMembershipRow"]] = relationship(back_populates="user")


class TenantRow(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("source_mode IN ('synthetic', 'live')", name="ck_tenants_source_mode"),
    )

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    onboarding_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    memberships: Mapped[list["TenantMembershipRow"]] = relationship(back_populates="tenant")
    connections: Mapped[list["CloudConnectionRow"]] = relationship(back_populates="tenant")
    incidents: Mapped[list["IncidentRow"]] = relationship(back_populates="tenant")
    rca_cases: Mapped[list["RcaCaseRow"]] = relationship(back_populates="tenant")


class TenantMembershipRow(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_tenant_membership_user_tenant"),
        CheckConstraint(
            "role IN ('OWNER', 'OPERATOR', 'VIEWER')", name="ck_tenant_membership_role"
        ),
    )

    membership_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"tm-{__import__('uuid').uuid4()}"
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    user: Mapped[UserRow] = relationship(back_populates="memberships")
    tenant: Mapped[TenantRow] = relationship(back_populates="memberships")


class CloudConnectionRow(Base):
    __tablename__ = "cloud_connections"

    connection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    credentials_ciphertext: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    tenant: Mapped[TenantRow] = relationship(back_populates="connections")
    resources: Mapped[list["CloudResourceRow"]] = relationship(back_populates="connection")


class CloudResourceRow(Base):
    __tablename__ = "cloud_resources"

    resource_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_connections.connection_id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    connection: Mapped[CloudConnectionRow] = relationship(back_populates="resources")


class NotificationEndpointRow(Base):
    __tablename__ = "notification_endpoints"

    endpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    secret_ciphertext: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class NotificationPolicyRow(Base):
    __tablename__ = "notification_policies"

    policy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    match_criteria: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    retry_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class NotificationDeliveryRow(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("alert_id", "endpoint_id", name="uq_notification_delivery_alert_endpoint"),
    )

    delivery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    alert_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    endpoint_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class IncidentRow(Base):
    __tablename__ = "incidents"

    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    tenant: Mapped[TenantRow] = relationship(back_populates="incidents")

    def __getattr__(self, name: str):
        if name == "metadata":
            return self.details
        raise AttributeError(name)

    def __setattr__(self, name: str, value):
        if name == "metadata":
            object.__setattr__(self, "details", value)
            return
        super().__setattr__(name, value)


class RcaCaseRow(Base):
    __tablename__ = "rca_cases"

    rca_case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    tenant: Mapped[TenantRow] = relationship(back_populates="rca_cases")


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    audit_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


__all__ = [
    "Base",
    "UserRow",
    "TenantRow",
    "TenantMembershipRow",
    "CloudConnectionRow",
    "CloudResourceRow",
    "NotificationEndpointRow",
    "NotificationPolicyRow",
    "NotificationDeliveryRow",
    "IncidentRow",
    "RcaCaseRow",
    "AuditEventRow",
]
