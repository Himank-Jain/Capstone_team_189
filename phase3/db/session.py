"""Session factory for the Phase 3 platform schema."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class PlatformSessionFactory:
    """Build SQLAlchemy sessions from injected config values."""

    def __init__(self, cfg: dict | None):
        self._cfg = cfg or {}
        self._engine: Engine | None = None

    @property
    def cfg(self) -> dict:
        return self._cfg

    def build_engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        db_url = (
            self._cfg.get("database_url")
            or self._cfg.get("DATABASE_URL")
            or "sqlite:///./capstone_phase3_demo.db"
        )
        echo = bool(self._cfg.get("db_echo", False) or self._cfg.get("DB_ECHO", False))
        connect_args = {"check_same_thread": False} if db_url.startswith("sqlite:") else {}
        self._engine = create_engine(db_url, echo=echo, future=True, connect_args=connect_args)
        return self._engine

    def create_session(self) -> Session:
        engine = self.build_engine()
        session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        return session_factory()

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self.create_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


__all__ = ["PlatformSessionFactory"]
