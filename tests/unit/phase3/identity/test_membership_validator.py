from phase3.identity.membership_validator import MembershipValidator
from phase3.shared.types import Role, TenantMembership


class FakeMembershipReader:
    def __init__(self, memberships):
        self._memberships = memberships

    def fetch_membership(self, user_id: str, tenant_id: str):
        return self._memberships.get((user_id, tenant_id))


def test_membership_validator_handles_roles_and_tenant_checks():
    memberships = {
        ("user-1", "tenant-1"): TenantMembership(user_id="user-1", tenant_id="tenant-1", role=Role.OWNER),
        ("user-2", "tenant-1"): TenantMembership(user_id="user-2", tenant_id="tenant-1", role=Role.VIEWER),
    }
    validator = MembershipValidator(FakeMembershipReader(memberships))

    assert validator.validate("user-1", "tenant-1", Role.OWNER) is True
    assert validator.validate("user-1", "tenant-1", Role.OPERATOR) is True
    assert validator.validate("user-2", "tenant-1", Role.VIEWER) is True
    assert validator.validate("user-2", "tenant-1", Role.OPERATOR) is False
    assert validator.validate("user-2", "tenant-2", Role.VIEWER) is False
    assert validator.validate("missing", "tenant-1", Role.VIEWER) is False
