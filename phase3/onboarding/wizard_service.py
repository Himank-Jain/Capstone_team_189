"""Onboarding state machine for tenant activation and monitoring setup."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class OnboardingWizardService:
    """Small, resilient orchestration service for onboarding progress."""

    def __init__(self, *args, **kwargs):
        self._sessions: dict[str, dict[str, Any]] = {}

    def start_onboarding(self, user_id: str, tenant_name: str, source_mode: str = "synthetic") -> dict[str, Any]:
        session_id = f"onboarding-{user_id}-{uuid4().hex}"
        session = {
            "session_id": session_id,
            "user_id": user_id,
            "tenant_name": tenant_name,
            "source_mode": source_mode,
            "status": "in_progress",
            "steps": {},
            "created_at": datetime.now(timezone.utc),
        }
        self._sessions[session_id] = session
        return session

    def start(self, user_id: str, tenant_name: str, source_mode: str = "synthetic") -> dict[str, Any]:
        return self.start_onboarding(user_id, tenant_name, source_mode)

    def record_step(self, session_id: str, step_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self._sessions[session_id]
        session.setdefault("steps", {})[step_name] = payload or {}
        session["status"] = "in_progress"
        return session

    def advance(self, session_id: str, step_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.record_step(session_id, step_name, payload)

    def mark_complete(self, session_id: str, step_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self._sessions[session_id]
        session.setdefault("steps", {})[step_name] = payload or {}
        session["status"] = "complete"
        return session

    def complete(self, session_id: str, step_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.mark_complete(session_id, step_name, payload)

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._sessions[session_id]

    def restore_session(self, session: dict[str, Any]) -> dict[str, Any]:
        session_id = str(session["session_id"])
        self._sessions[session_id] = session
        return session

    def get_sessions_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return [session for session in self._sessions.values() if session.get("user_id") == user_id]


__all__ = ["OnboardingWizardService"]
