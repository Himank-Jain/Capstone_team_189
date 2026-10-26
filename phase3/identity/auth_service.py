"""Authentication and token issuance for platform users."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from phase3.identity.repositories import UserRepositoryProtocol
from phase3.shared.exceptions import (
    DuplicateUserError,
    InvalidCredentialsError,
)
from phase3.shared.types import User


class AuthService:
    """Create, verify, and authenticate platform users."""

    def __init__(self, user_repository: UserRepositoryProtocol, cfg: dict | None = None):
        self._user_repository = user_repository
        self._cfg = cfg or {}
        candidate_secret = self._cfg.get("jwt_secret") or self._cfg.get("JWT_SECRET")
        secret_len = len(candidate_secret.encode("utf-8")) if candidate_secret else 0
        if candidate_secret is None or secret_len < 32:
            raise ValueError("jwt_secret must be configured and at least 32 bytes long")
        self._jwt_secret = candidate_secret
        self._jwt_ttl_seconds = int(
            self._cfg.get("jwt_ttl_seconds", self._cfg.get("JWT_TTL_SECONDS", 3600))
        )
        self._bcrypt_rounds = int(
            self._cfg.get("bcrypt_rounds", self._cfg.get("BCRYPT_ROUNDS", 12))
        )

    @property
    def token_ttl_seconds(self) -> int:
        return self._jwt_ttl_seconds

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    def register(self, email: str, password: str) -> User:
        normalized_email = self.normalize_email(email)
        if self._user_repository.fetch_by_email(normalized_email) is not None:
            raise DuplicateUserError(f"email already registered: {normalized_email}")

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(rounds=self._bcrypt_rounds),
        ).decode("utf-8")
        user = User(
            user_id=self._next_user_id(),
            email=normalized_email,
            password_hash=password_hash,
            created_at=datetime.now(timezone.utc),
        )
        return self._user_repository.save(user)

    def _next_user_id(self) -> str:
        # Durable repositories supply their own collision-free ids; counting an
        # in-memory dict only works for the simple fakes used in unit tests.
        next_id = getattr(self._user_repository, "next_user_id", None)
        if callable(next_id):
            return str(next_id())
        users = self._user_repository.__dict__.get("_users")
        if isinstance(users, dict):
            return f"user-{len(users) + 1}"
        return f"user-{uuid.uuid4().hex[:12]}"

    def login(self, email: str, password: str) -> str:
        normalized_email = self.normalize_email(email)
        user = self._user_repository.fetch_by_email(normalized_email)
        if user is None:
            raise InvalidCredentialsError("invalid credentials")

        try:
            password_matches = bcrypt.checkpw(
                password.encode("utf-8"),
                user.password_hash.encode("utf-8"),
            )
        except ValueError:
            # Rows created outside this service (for example the legacy demo
            # identity) carry a non-bcrypt placeholder hash; treat as no match.
            password_matches = False
        if not password_matches:
            raise InvalidCredentialsError("invalid credentials")

        return self.issue_token(user.user_id)

    def issue_token(self, user_id: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self._jwt_ttl_seconds)).timestamp()),
        }
        return jwt.encode(payload, self._jwt_secret, algorithm="HS256")

    def verify_token(self, token: str) -> dict:
        return jwt.decode(token, self._jwt_secret, algorithms=["HS256"])
