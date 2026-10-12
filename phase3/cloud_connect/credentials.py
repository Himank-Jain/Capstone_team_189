"""Credential storage helpers for cloud connections."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet


class CredentialStore:
    """Encrypt credentials at rest and expose a small in-memory store."""

    def __init__(self, key: str | None = None):
        secret = (key or "").strip()
        if not secret or len(secret.encode("utf-8")) < 32:
            raise ValueError(
                "CredentialStore requires a configured Fernet key " "at least 32 bytes long"
            )
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(digest)
        self._fernet = Fernet(fernet_key)
        self._vault: dict[str, str] = {}

    def save(
        self,
        tenant_id: str,
        provider: str,
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        serialized = self._fernet.encrypt(repr(credentials).encode("utf-8"))
        self._vault[f"{tenant_id}:{provider}"] = serialized.decode("utf-8")
        return dict(credentials)

    def load(self, tenant_id: str, provider: str) -> dict[str, Any] | None:
        token = self._vault.get(f"{tenant_id}:{provider}")
        if token is None:
            return None
        payload = self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        if payload.startswith("{'"):
            payload = payload.replace("'", '"')
        try:
            import json

            return json.loads(payload)
        except json.JSONDecodeError:
            return {"value": payload}

    def delete(self, tenant_id: str, provider: str) -> None:
        self._vault.pop(f"{tenant_id}:{provider}", None)
