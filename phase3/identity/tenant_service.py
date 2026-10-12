"""Tenant lifecycle service for Phase 3 identity and tenancy."""

from __future__ import annotations

from datetime import datetime, timezone

from phase3.identity.repositories import MembershipWriterProtocol, TenantRepositoryProtocol
from phase3.shared.constants import PLATFORM_SOURCE_MODE_LIVE, PLATFORM_SOURCE_MODE_SYNTHETIC
from phase3.shared.exceptions import TenantValidationError
from phase3.shared.types import Role, Tenant, TenantMembership


class TenantService:
    """Create tenants and attach owner memberships."""

    def __init__(
        self,
        tenant_repository: TenantRepositoryProtocol,
        membership_writer: MembershipWriterProtocol,
    ):
        self._tenant_repository = tenant_repository
        self._membership_writer = membership_writer

    def create_tenant(self, name: str, source_mode: str, creator_user_id: str) -> Tenant:
        if source_mode not in {PLATFORM_SOURCE_MODE_SYNTHETIC, PLATFORM_SOURCE_MODE_LIVE}:
            raise TenantValidationError(f"invalid source_mode: {source_mode}")

        tenant = Tenant(
            tenant_id=f"tenant-{creator_user_id}",
            name=name,
            source_mode=source_mode,
            created_at=datetime.now(timezone.utc),
        )
        saved = self._tenant_repository.save(tenant)
        self._membership_writer.create_membership(
            TenantMembership(user_id=creator_user_id, tenant_id=saved.tenant_id, role=Role.OWNER)
        )
        return saved

    def ensure_source_mode_is_immutable(self, tenant: Tenant, next_source_mode: str) -> None:
        if tenant.source_mode != next_source_mode and tenant.source_mode in {
            PLATFORM_SOURCE_MODE_SYNTHETIC,
            PLATFORM_SOURCE_MODE_LIVE,
        }:
            raise TenantValidationError("source_mode is immutable once set")
