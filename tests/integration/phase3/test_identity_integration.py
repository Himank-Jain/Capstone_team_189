from datetime import datetime, timezone

import bcrypt

from phase3.identity.auth_service import AuthService
from phase3.identity.membership_validator import MembershipValidator
from phase3.shared.types import Role, TenantMembership


class FakeUserRepository:
    def __init__(self):
        self._users = {}

    def fetch_by_email(self, email: str):
        return self._users.get(email)

    def save(self, user):
        self._users[user.email] = user
        return user


class FakeMembershipReader:
    def __init__(self):
        self._memberships = {
            ("user-1", "tenant-1"): TenantMembership(user_id="user-1", tenant_id="tenant-1", role=Role.OWNER),
            ("user-2", "tenant-1"): TenantMembership(user_id="user-2", tenant_id="tenant-1", role=Role.VIEWER),
        }

    def fetch_membership(self, user_id: str, tenant_id: str):
        return self._memberships.get((user_id, tenant_id))


def test_auth_service_and_validator_work_together():
    repo = FakeUserRepository()
    service = AuthService(repo, {"bcrypt_rounds": 12, "jwt_secret": "test-secret-32-bytes-long-enough-for-jwt"})
    validator = MembershipValidator(FakeMembershipReader())

    user = service.register("owner@example.com", "Secret123!")
    token = service.login("owner@example.com", "Secret123!")
    payload = service.verify_token(token)

    assert payload["sub"] == user.user_id
    assert bcrypt.checkpw("Secret123!".encode("utf-8"), user.password_hash.encode("utf-8"))
    assert validator.validate(user.user_id, "tenant-1", Role.OWNER) is True
    assert validator.validate("user-2", "tenant-1", Role.OPERATOR) is False
