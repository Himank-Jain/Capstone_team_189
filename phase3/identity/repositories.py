"""Repository interfaces used by the identity layer."""

from __future__ import annotations

from typing import Protocol

from phase3.shared.types import Role, Tenant, TenantMembership, User


class UserRepositoryProtocol(Protocol):
    def fetch_by_email(self, email: str) -> User | None:
        ...

    def save(self, user: User) -> User:
        ...


class TenantRepositoryProtocol(Protocol):
    def fetch_by_id(self, tenant_id: str) -> Tenant | None:
        ...

    def save(self, tenant: Tenant) -> Tenant:
        ...


class MembershipReaderProtocol(Protocol):
    def fetch_membership(self, user_id: str, tenant_id: str) -> TenantMembership | None:
        ...


class MembershipWriterProtocol(Protocol):
    def create_membership(self, membership: TenantMembership) -> TenantMembership:
        ...

    def fetch_role(self, user_id: str, tenant_id: str) -> Role | None:
        ...
