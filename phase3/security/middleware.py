"""Request-level tenant authorization checks for the Phase 3 security hardening pass."""

from __future__ import annotations

from typing import Any

from phase3.identity.membership_validator import MembershipValidator


class TenantIsolationMiddleware:
    """Enforce tenant membership and reject cross-tenant requests before routing."""

    def __init__(self, membership_validator: MembershipValidator, required_role: str = "VIEWER"):
        self._membership_validator = membership_validator
        self._required_role = required_role

    def authorize(self, request: Any, tenant_id: str | None = None, required_role: str | None = None) -> bool:
        session = getattr(request, "session", {}) or {}
        if isinstance(session, dict):
            user_id = session.get("user_id")
            current_tenant = session.get("tenant_id")
        else:
            user_id = getattr(session, "get", lambda *_args, **_kwargs: None)("user_id")
            current_tenant = getattr(session, "get", lambda *_args, **_kwargs: None)("tenant_id")

        resolved_tenant = tenant_id or current_tenant
        if not user_id or not resolved_tenant:
            raise PermissionError("authenticated user and tenant are required")

        if tenant_id is not None and tenant_id != current_tenant:
            raise PermissionError("cross-tenant request rejected")

        effective_role = required_role or self._required_role
        if not self._membership_validator.validate(str(user_id), str(resolved_tenant), effective_role):
            raise PermissionError("tenant access denied")
        return True


class CredentialRedactionFilter:
    """Mask values for credentials and tokens in structured payloads."""

    @staticmethod
    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            redacted = {}
            for key, item in value.items():
                if any(token in str(key).lower() for token in ("secret", "token", "password", "key")):
                    redacted[key] = "***redacted***"
                else:
                    redacted[key] = CredentialRedactionFilter.redact(item)
            return redacted
        if isinstance(value, list):
            return [CredentialRedactionFilter.redact(item) for item in value]
        return value


__all__ = ["TenantIsolationMiddleware", "CredentialRedactionFilter"]
