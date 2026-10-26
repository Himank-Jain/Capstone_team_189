"""SQLAlchemy-backed user repository for the platform identity layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from typing import Callable, Union

from phase3.db.models import UserRow
from phase3.db.session import PlatformSessionFactory
from phase3.shared.types import User


class SqlUserRepository:
    """Persist and look up platform users in the ``users`` table."""

    def __init__(
        self,
        session_factory: Union[PlatformSessionFactory, Callable[[], PlatformSessionFactory]],
    ):
        # Accept a provider so callers that swap the active factory (tests,
        # reconfiguration) are always honoured.
        self._factory_source = session_factory

    @property
    def _session_factory(self) -> PlatformSessionFactory:
        source = self._factory_source
        return source if isinstance(source, PlatformSessionFactory) else source()

    @staticmethod
    def _to_user(row: UserRow) -> User:
        created_at = row.created_at or datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return User(
            user_id=row.user_id,
            email=row.email,
            password_hash=row.password_hash,
            created_at=created_at,
        )

    @staticmethod
    def next_user_id() -> str:
        return f"user-{uuid.uuid4().hex[:12]}"

    def fetch_by_email(self, email: str) -> User | None:
        with self._session_factory.session_scope() as session:
            row = session.query(UserRow).filter_by(email=email).one_or_none()
            return self._to_user(row) if row is not None else None

    def fetch_by_id(self, user_id: str) -> User | None:
        with self._session_factory.session_scope() as session:
            row = session.get(UserRow, user_id)
            return self._to_user(row) if row is not None else None

    def save(self, user: User) -> User:
        with self._session_factory.session_scope() as session:
            row = session.get(UserRow, user.user_id)
            if row is None:
                session.add(
                    UserRow(
                        user_id=user.user_id,
                        email=user.email,
                        password_hash=user.password_hash,
                        created_at=user.created_at,
                    )
                )
            else:
                row.email = user.email
                row.password_hash = user.password_hash
        return user


__all__ = ["SqlUserRepository"]
