"""Role-based tenant membership validation."""

from __future__ import annotations

from phase3.identity.repositories import MembershipReaderProtocol
from phase3.shared.types import Role


class MembershipValidator:
    """Validate a user's role in a tenant."""

    def __init__(self, membership_reader: MembershipReaderProtocol):
        self._membership_reader = membership_reader

    def validate(self, user_id: str, tenant_id: str, min_role: Role | str) -> bool:
        required_role = Role(min_role) if isinstance(min_role, str) else min_role
        membership = self._membership_reader.fetch_membership(user_id, tenant_id)
        if membership is None:
            return False

        current_role = membership.role
        if isinstance(current_role, str):
            try:
                current_role = Role(current_role)
            except ValueError:
                return False

        if current_role not in Role:
            return False

        rank = {Role.OWNER: 3, Role.OPERATOR: 2, Role.VIEWER: 1}
        return rank.get(current_role, 0) >= rank.get(required_role, 0)
