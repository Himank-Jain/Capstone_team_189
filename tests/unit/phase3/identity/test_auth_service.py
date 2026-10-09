from datetime import datetime, timezone

import bcrypt
import pytest

from phase3.identity.auth_service import AuthService
from phase3.shared.exceptions import DuplicateUserError, InvalidCredentialsError
from phase3.shared.types import User


class FakeUserRepository:
    def __init__(self):
        self._users = {}

    def fetch_by_email(self, email: str):
        return self._users.get(email)

    def save(self, user: User) -> User:
        self._users[user.email] = user
        return user


def test_register_hashes_password_and_normalizes_email():
    repo = FakeUserRepository()
    service = AuthService(repo, {"bcrypt_rounds": 12, "jwt_secret": "test-secret-32-bytes-long-enough-for-jwt"})

    user = service.register("  Alice@Example.com ", "Secret123!")

    assert user.email == "alice@example.com"
    assert user.password_hash != "Secret123!"
    assert bcrypt.checkpw("Secret123!".encode("utf-8"), user.password_hash.encode("utf-8"))


def test_login_rejects_unknown_user_without_leaking_email():
    repo = FakeUserRepository()
    service = AuthService(repo, {"bcrypt_rounds": 12, "jwt_secret": "test-secret-32-bytes-long-enough-for-jwt"})

    with pytest.raises(InvalidCredentialsError):
        service.login("missing@example.com", "bad-pass")


def test_duplicate_email_is_rejected():
    repo = FakeUserRepository()
    service = AuthService(repo, {"bcrypt_rounds": 12, "jwt_secret": "test-secret-32-bytes-long-enough-for-jwt"})
    service.register("user@example.com", "Secret123!")

    with pytest.raises(DuplicateUserError):
        service.register("USER@example.com", "Otherpass")


def test_auth_service_requires_configured_secret_of_at_least_32_bytes():
    repo = FakeUserRepository()

    with pytest.raises(ValueError, match="jwt_secret"):
        AuthService(repo, {"jwt_secret": "short"})

    with pytest.raises(ValueError, match="jwt_secret"):
        AuthService(repo, {})
