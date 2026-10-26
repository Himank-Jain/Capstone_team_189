from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from phase3.api.app import (
    DEMO_DEDUP_REDIS,
    DEMO_STATE,
    _BASELINE_LIFECYCLE,
    _DRIFT_SCORE_CACHE,
    _update_recovery_state,
    alerts_by_tenant,
    app,
)
from phase3.api.routers import _support
from phase3.db.models import (
    AuditEventRow,
    Base,
    IncidentRow,
    TenantMembershipRow,
    TenantRow,
    UserRow,
)
from phase3.db.session import PlatformSessionFactory


@pytest.fixture
def lifecycle_client(tmp_path, monkeypatch):
    factory = PlatformSessionFactory(
        {"database_url": f"sqlite:///{tmp_path / 'incident-lifecycle.db'}"}
    )
    Base.metadata.create_all(factory.build_engine())
    monkeypatch.setattr(_support, "platform_session_factory", factory)

    now = datetime.now(timezone.utc)
    with factory.session_scope() as session:
        session.add_all(
            [
                TenantRow(tenant_id="tenant-a", name="A", source_mode="synthetic"),
                TenantRow(tenant_id="tenant-b", name="B", source_mode="synthetic"),
                UserRow(user_id="operator-a", email="operator-a@test", password_hash="x"),
                UserRow(user_id="viewer-a", email="viewer-a@test", password_hash="x"),
                UserRow(user_id="owner-b", email="owner-b@test", password_hash="x"),
                TenantMembershipRow(
                    membership_id="membership-op",
                    user_id="operator-a",
                    tenant_id="tenant-a",
                    role="OPERATOR",
                ),
                TenantMembershipRow(
                    membership_id="membership-viewer",
                    user_id="viewer-a",
                    tenant_id="tenant-a",
                    role="VIEWER",
                ),
                TenantMembershipRow(
                    membership_id="membership-owner-b",
                    user_id="owner-b",
                    tenant_id="tenant-b",
                    role="OWNER",
                ),
                IncidentRow(
                    incident_id="incident-a",
                    tenant_id="tenant-a",
                    entity_id="entity-a",
                    severity="HIGH",
                    status="open",
                    first_seen_at=now,
                    last_seen_at=now,
                    details={"incident_group_id": "group-a"},
                ),
                IncidentRow(
                    incident_id="incident-b",
                    tenant_id="tenant-b",
                    entity_id="entity-b",
                    severity="HIGH",
                    status="OPEN",
                    first_seen_at=now,
                    last_seen_at=now,
                ),
            ]
        )

    with TestClient(app) as client:
        yield client, factory


def test_lifecycle_transitions_are_tenant_scoped_role_checked_and_audited(lifecycle_client):
    client, factory = lifecycle_client
    operator_headers = {"X-Tenant-Id": "tenant-a", "X-User-Id": "operator-a"}
    viewer_headers = {"X-Tenant-Id": "tenant-a", "X-User-Id": "viewer-a"}

    assert client.post(
        "/incidents/incident-a/resolve",
        headers=viewer_headers,
        json={"resolution_type": "FIXED", "note": "no"},
    ).status_code == 403
    assert (
        client.get("/incidents/incident-b/lifecycle", headers=operator_headers).status_code
        == 404
    )
    assert client.post(
        "/incidents/incident-b/resolve",
        headers=operator_headers,
        json={"resolution_type": "FIXED", "note": "cross tenant"},
    ).status_code == 404

    DEMO_DEDUP_REDIS.set("dedup:entity-a:123", "tracked")
    _DRIFT_SCORE_CACHE[("tenant-a", "entity-a")] = 0.7
    acknowledged = client.post(
        "/incidents/incident-a/acknowledge", headers=operator_headers
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "ACKNOWLEDGED"
    assert _BASELINE_LIFECYCLE[("tenant-a", "entity-a")]["frozen"] is True
    for _ in range(6):
        _update_recovery_state("tenant-a", "entity-a", 0.1)
    lifecycle = client.get(
        "/incidents/incident-a/lifecycle", headers=operator_headers
    ).json()
    assert lifecycle["recovering"] is True
    assert client.post(
        "/incidents/incident-a/acknowledge", headers=operator_headers
    ).json()["status"] == "ACKNOWLEDGED"

    resolved = client.post(
        "/incidents/incident-a/resolve",
        headers=operator_headers,
        json={"resolution_type": "FIXED", "note": "contained"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"
    assert DEMO_DEDUP_REDIS.get("dedup:entity-a:123") is None
    assert ("tenant-a", "entity-a") not in _DRIFT_SCORE_CACHE
    assert _BASELINE_LIFECYCLE[("tenant-a", "entity-a")]["frozen"] is False
    resolved_summary = client.get("/stats/summary", headers={"X-Tenant-Id": "tenant-a"}).json()
    assert resolved_summary["active_incidents"] == 0
    assert resolved_summary["resolved_today"] == 1
    assert client.get("/alerts/recent", headers={"X-Tenant-Id": "tenant-a"}).json() == []
    assert resolved.json()["resolved_by"] == "operator-a"
    assert client.post(
        "/incidents/incident-a/resolve",
        headers=operator_headers,
        json={"resolution_type": "FIXED", "note": "repeat"},
    ).json()["resolution_note"] == "contained"
    assert client.post(
        "/incidents/incident-a/acknowledge", headers=operator_headers
    ).status_code == 409

    reopened = client.post("/incidents/incident-a/reopen", headers=operator_headers)
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "OPEN"
    assert _BASELINE_LIFECYCLE[("tenant-a", "entity-a")]["frozen"] is True
    assert client.post("/incidents/incident-a/reopen", headers=operator_headers).status_code == 409

    with factory.session_scope() as session:
        audit_rows = session.query(AuditEventRow).filter_by(
            tenant_id="tenant-a", target="incident-a"
        ).all()
        actions = {row.action for row in audit_rows}
        resolve_events = [
            row
            for row in audit_rows
            if row.action == "incident_resolved"
        ]
    assert {"incident_acknowledged", "incident_resolved", "incident_reopened"} <= actions
    assert len(resolve_events) == 1


def test_fixed_resolution_reinjection_creates_fresh_linked_incident(lifecycle_client):
    client, factory = lifecycle_client
    headers = _support.provision_demo_identity()
    headers = {"X-Tenant-Id": "google", "X-User-Id": headers}
    DEMO_STATE.clear()
    alerts_by_tenant.clear()
    DEMO_DEDUP_REDIS.delete_by_prefix("dedup:vol-g00g:")
    _BASELINE_LIFECYCLE.pop(("google", "vol-g00g"), None)

    request_body = {
        "tenant_id": "google",
        "scenario": "credential_theft",
        "mode": "attack",
        "seed": 13,
    }
    first = client.post("/demo/generate/attack", headers=headers, json=request_body)
    assert first.status_code == 200, first.text
    first_payload = first.json()["alert_payload"]
    first_id = first_payload["alert_id"]

    resolved = client.post(
        f"/incidents/{first_id}/resolve",
        headers=headers,
        json={"resolution_type": "FIXED", "note": "credential rotated"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"

    second = client.post("/demo/generate/attack", headers=headers, json=request_body)
    assert second.status_code == 200, second.text
    second_payload = second.json()["alert_payload"]
    assert second_payload["alert_id"] != first_id
    assert second_payload["history_context"]["duplicate"] is False
    assert second_payload["regression_of"] == first_id
    assert second_payload["sev_level"] == first_payload["sev_level"]
    active_summary = client.get("/stats/summary", headers={"X-Tenant-Id": "google"}).json()
    assert active_summary["active_incidents"] == 1
    assert active_summary["mean_time_to_resolve_minutes"] >= 0
    recent = client.get("/alerts/recent", headers={"X-Tenant-Id": "google"}).json()
    assert [row["alert_id"] for row in recent] == [second_payload["alert_id"]]

    with factory.session_scope() as session:
        new_incident = session.query(IncidentRow).filter_by(
            tenant_id="google", incident_id=second_payload["alert_id"]
        ).one()
    assert new_incident.status == "OPEN"
    assert new_incident.regression_of == first_id
