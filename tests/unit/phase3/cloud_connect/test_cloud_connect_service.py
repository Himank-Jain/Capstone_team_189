from __future__ import annotations

from phase3.cloud_connect.credentials import CredentialStore
from phase3.cloud_connect.service import (
    CloudConnection,
    CloudConnectionService,
)


class StubConnector:
    def __init__(self, healthy: bool = True):
        self.healthy = healthy

    def health_check(self) -> bool:
        return self.healthy

    def list_resources(self):
        return [{
            "resource_id": "res-1",
            "resource_type": "VirtualMachine",
            "resource_name": "vm-01",
        }]


def test_credential_store_round_trip_and_service_validation():
    store = CredentialStore(key="0123456789abcdef0123456789abcdef")
    service = CloudConnectionService(credential_store=store)
    connection = CloudConnection(
        connection_id="conn-1",
        tenant_id="tenant-1",
        provider="AWS",
        credentials={"api_key": "super-secret"},
        dry_run=True,
    )

    stored = service.save_connection(connection)
    assert stored.credentials_cfg["api_key"] == "super-secret"

    assert service.validate_connection(stored, StubConnector()) is True

    resources = service.list_resources(stored, StubConnector())
    assert resources[0].resource_id == "res-1"
    assert resources[0].resource_name == "vm-01"


def test_credential_store_requires_valid_fernet_key():
    try:
        CredentialStore(key="short")
    except ValueError as exc:
        assert "fernet" in str(exc).lower()
    else:
        raise AssertionError("CredentialStore accepted an invalid key")
