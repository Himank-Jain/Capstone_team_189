from dataclasses import asdict
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastapi.encoders import jsonable_encoder

from phase3.api.app import app
from phase3.db.models import (
    Base,
    CloudConnectionRow,
    IncidentRow,
    NotificationEndpointRow,
    RcaCaseRow,
    TenantMembershipRow,
    TenantRow,
    UserRow,
)
from phase3.db.session import PlatformSessionFactory
from phase3.identity.membership_validator import MembershipValidator
from phase3.rca.types import CandidateCause, RCACase
from phase3.security.middleware import TenantIsolationMiddleware


def _case_payload(tenant_id, incident_id, rca_case_id, provider):
    case = RCACase(
        rca_case_id=rca_case_id,
        incident_id=incident_id,
        tenant_id=tenant_id,
        entity_id=f"entity-{tenant_id[-1]}",
        batch_ts=datetime(2026, 10, 14, tzinfo=timezone.utc),
        cloud_provider=provider,
        region="us-east-1",
        final_score=0.1,
        severity="LOW",
        component_scores={},
        candidate_causes=[
            CandidateCause(
                cause_category="UNKNOWN",
                confidence="LOW",
                rule_id="test.unknown",
                supporting_evidence_keys=[],
                contradicting_evidence_keys=[],
            )
        ],
    )
    return jsonable_encoder(asdict(case))


@pytest.fixture
def tenant_isolation_client(tmp_path, monkeypatch):
    from phase3.api.routers import _support

    factory = PlatformSessionFactory(
        {"database_url": f"sqlite:///{tmp_path / 'tenant-isolation.db'}"}
    )
    Base.metadata.create_all(factory.build_engine())
    monkeypatch.setattr(_support, "platform_session_factory", factory)
    monkeypatch.setattr(_support, "rca_cases", {})
    monkeypatch.setattr(_support, "onboarding_tenant_ids", {})

    now = datetime.now(timezone.utc)
    with factory.session_scope() as session:
        session.add_all(
            [
                TenantRow(tenant_id="tenant-a", name="Tenant A", source_mode="synthetic"),
                TenantRow(tenant_id="tenant-b", name="Tenant B", source_mode="synthetic"),
                UserRow(user_id="user-a", email="a@example.test", password_hash="hash-a"),
                UserRow(user_id="user-b", email="b@example.test", password_hash="hash-b"),
                UserRow(
                    user_id="user-a-viewer",
                    email="a-viewer@example.test",
                    password_hash="hash-viewer",
                ),
                UserRow(
                    user_id="user-a-operator",
                    email="a-operator@example.test",
                    password_hash="hash-operator",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                TenantMembershipRow(
                    membership_id="membership-a",
                    user_id="user-a",
                    tenant_id="tenant-a",
                    role="OWNER",
                ),
                TenantMembershipRow(
                    membership_id="membership-b",
                    user_id="user-b",
                    tenant_id="tenant-b",
                    role="OWNER",
                ),
                TenantMembershipRow(
                    membership_id="membership-a-viewer",
                    user_id="user-a-viewer",
                    tenant_id="tenant-a",
                    role="VIEWER",
                ),
                TenantMembershipRow(
                    membership_id="membership-a-operator",
                    user_id="user-a-operator",
                    tenant_id="tenant-a",
                    role="OPERATOR",
                ),
                CloudConnectionRow(
                    connection_id="connection-a",
                    tenant_id="tenant-a",
                    provider="AWS",
                    status="connected",
                ),
                CloudConnectionRow(
                    connection_id="connection-b",
                    tenant_id="tenant-b",
                    provider="Azure",
                    status="connected",
                ),
                NotificationEndpointRow(
                    endpoint_id="endpoint-a",
                    tenant_id="tenant-a",
                    channel="EMAIL",
                    target="a@example.test",
                ),
                NotificationEndpointRow(
                    endpoint_id="endpoint-b",
                    tenant_id="tenant-b",
                    channel="EMAIL",
                    target="b@example.test",
                ),
            ]
        )
        for tenant_id, incident_id, rca_id, delivery_id in (
            ("tenant-a", "incident-a", "rca-a", "delivery-a"),
            ("tenant-b", "incident-b", "rca-b", "delivery-b"),
        ):
            session.add(
                IncidentRow(
                    incident_id=incident_id,
                    tenant_id=tenant_id,
                    entity_id=f"entity-{tenant_id[-1]}",
                    severity="HIGH",
                    status="open",
                    first_seen_at=now,
                    last_seen_at=now,
                    details={"source": "test"},
                )
            )
            session.add(
                RcaCaseRow(
                    rca_case_id=rca_id,
                    incident_id=incident_id,
                    tenant_id=tenant_id,
                    title=f"Case {tenant_id}",
                    body={
                        "case": _case_payload(
                            tenant_id,
                            incident_id,
                            rca_id,
                            "AWS" if tenant_id == "tenant-a" else "Azure",
                        ),
                        "explanation": {"rca_case_id": rca_id},
                        "recommendations": [{"check": f"check-{tenant_id}"}],
                        "notification_deliveries": [{"delivery_id": delivery_id}],
                    },
                )
            )

    with TestClient(app) as client:
        yield client, factory


def test_phase3_routes_do_not_expose_tenant_b_records_to_tenant_a(tenant_isolation_client):
    client, _factory = tenant_isolation_client
    headers = {
        "X-Tenant-Id": "tenant-a",
        "X-User-Id": "user-a",
        "Authorization": "Bearer user-a-test-token",
    }

    connections = client.get("/connections", headers=headers)
    incidents = client.get("/incidents", headers=headers)
    incident = client.get("/incidents/incident-b", headers=headers)
    explanation = client.get("/incidents/incident-b/explanation", headers=headers)
    recommendations = client.get("/incidents/incident-b/recommendations", headers=headers)
    deliveries = client.get("/notification-deliveries", headers=headers)

    assert connections.status_code == 200
    assert connections.json()["tenant_id"] == "tenant-a"
    assert "connection-b" not in connections.text

    assert incidents.status_code == 200
    assert [row["incident_id"] for row in incidents.json()] == ["incident-a"]
    assert incident.status_code == 404
    assert explanation.status_code == 404
    assert recommendations.status_code == 404
    assert deliveries.status_code == 200
    assert [row["delivery_id"] for row in deliveries.json()] == ["delivery-a"]


def test_spoofed_tenant_path_parameter_is_rejected_before_membership_lookup():
    membership_lookups = []

    class MembershipReader:
        def fetch_membership(self, user_id, tenant_id):
            membership_lookups.append((user_id, tenant_id))
            return None

    middleware = TenantIsolationMiddleware(MembershipValidator(MembershipReader()))
    request = SimpleNamespace(session={"user_id": "user-a", "tenant_id": "tenant-a"})

    with pytest.raises(PermissionError, match="cross-tenant request rejected"):
        middleware.authorize(request, tenant_id="tenant-b")

    assert membership_lookups == []


def test_tenants_router_owns_scoped_onboarding_routes(tenant_isolation_client):
    client, _factory = tenant_isolation_client
    headers_a = {"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"}
    headers_b = {"X-Tenant-Id": "tenant-b", "X-User-Id": "user-b"}

    started = client.post(
        "/onboarding",
        headers=headers_a,
        json={"tenant_name": "Tenant A onboarding"},
    )
    assert started.status_code == 200
    session_id = started.json()["session_id"]
    assert client.get(f"/onboarding/{session_id}", headers=headers_a).status_code == 200
    assert client.get(f"/onboarding/{session_id}", headers=headers_b).status_code == 404


def test_cloud_connections_router_requires_tenant_membership(tenant_isolation_client):
    client, _factory = tenant_isolation_client
    own_headers = {"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"}
    spoofed_headers = {"X-Tenant-Id": "tenant-b", "X-User-Id": "user-a"}

    own_response = client.get("/connections", headers=own_headers)
    spoofed_response = client.get("/connections", headers=spoofed_headers)

    assert own_response.status_code == 200
    assert own_response.json()["tenant_id"] == "tenant-a"
    assert spoofed_response.status_code == 403


def test_incidents_router_returns_only_members_incidents(tenant_isolation_client):
    client, _factory = tenant_isolation_client
    headers = {"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"}

    incidents = client.get("/incidents", headers=headers)
    other_tenant_incident = client.get("/incidents/incident-b", headers=headers)

    assert [item["incident_id"] for item in incidents.json()] == ["incident-a"]
    assert other_tenant_incident.status_code == 404


def test_membership_role_is_returned_from_authoritative_tenant_membership(
    tenant_isolation_client,
):
    client, _factory = tenant_isolation_client
    owner_role = client.get(
        "/membership/role",
        headers={"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"},
    )
    viewer_role = client.get(
        "/membership/role",
        headers={"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a-viewer"},
    )
    cross_tenant_role = client.get(
        "/membership/role",
        headers={"X-Tenant-Id": "tenant-b", "X-User-Id": "user-a"},
    )

    assert owner_role.status_code == 200
    assert owner_role.json() == {"role": "OWNER"}
    assert viewer_role.status_code == 200
    assert viewer_role.json() == {"role": "VIEWER"}
    assert cross_tenant_role.status_code == 403


def test_incidents_list_includes_lifecycle_filter_and_regression_metadata(
    tenant_isolation_client,
):
    client, factory = tenant_isolation_client
    with factory.session_scope() as session:
        incident = session.get(IncidentRow, "incident-a")
        incident.status = "RESOLVED"
        incident.regression_of = "incident-original-a"
        incident.details = {"recovering": False}

    response = client.get(
        "/incidents",
        headers={"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"},
    )
    assert response.status_code == 200
    assert response.json()[0]["lifecycle_status"] == "RESOLVED"
    assert response.json()[0]["regression_of"] == "incident-original-a"
    assert response.json()[0]["recovering"] is False


def test_notifications_router_returns_only_members_deliveries(tenant_isolation_client):
    client, _factory = tenant_isolation_client
    headers = {"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"}

    deliveries = client.get("/notification-deliveries", headers=headers)

    assert deliveries.status_code == 200
    assert [item["delivery_id"] for item in deliveries.json()] == ["delivery-a"]


def test_rca_router_serves_scoped_explanations_and_recommendations(tenant_isolation_client):
    client, _factory = tenant_isolation_client
    headers = {"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"}

    explanation = client.get("/incidents/incident-a/explanation", headers=headers)
    recommendations = client.get("/incidents/incident-a/recommendations", headers=headers)
    other_explanation = client.get("/incidents/incident-b/explanation", headers=headers)
    other_recommendations = client.get("/incidents/incident-b/recommendations", headers=headers)

    assert explanation.status_code == 200
    assert explanation.json()["rca_case_id"] == "rca-a"
    assert explanation.json()["matched_threats"] == []
    assert explanation.json()["mitigation_mode"] == "generic"
    assert recommendations.status_code == 200
    assert recommendations.json()
    assert recommendations.json()[0]["check"]
    assert other_explanation.status_code == 404
    assert other_recommendations.status_code == 404


def test_mitigation_endpoint_is_role_scoped_and_read_only(tenant_isolation_client):
    client, factory = tenant_isolation_client
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    case = RCACase(
        rca_case_id="rca-a",
        incident_id="incident-a",
        tenant_id="tenant-a",
        entity_id="${severity}",
        batch_ts=now,
        cloud_provider="AWS",
        region="us-east-1",
        final_score=0.91,
        severity="HIGH",
        component_scores={"deviation": 0.9, "drift": 0.7, "similarity": 0.2},
        changed_features=["metric_family:api_calls"],
        observed_window={
            "metric_directions": {
                "api_calls": "increase",
                "auth_failures": "increase",
            },
            "entity_types": ["Instances"],
            "namespaces": ["AWS/EC2"],
        },
        candidate_causes=[
            CandidateCause(
                cause_category="CREDENTIAL_THEFT",
                confidence="HIGH",
                rule_id="test.credential",
                supporting_evidence_keys=["changed_features"],
                contradicting_evidence_keys=[],
            )
        ],
        confidence="HIGH",
    )
    with factory.session_scope() as session:
        incident = session.get(IncidentRow, "incident-a")
        incident.status = "resolved"
        incident.details = {
            "resolution_record": {
                "type": "contained",
                "who": "operator-a",
                "when": now.isoformat(),
                "note": "Credential review completed.",
            }
        }
        row = session.get(RcaCaseRow, "rca-a")
        row.body = {**row.body, "case": jsonable_encoder(asdict(case))}
        before_incident_details = dict(incident.details)
        before_rca_body = dict(row.body)

    role_headers = [
        {"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"},
        {"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a-viewer"},
        {"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a-operator"},
    ]
    responses = [
        client.get("/incidents/incident-a/mitigation", headers=headers)
        for headers in role_headers
    ]
    explanation = client.get(
        "/incidents/incident-a/explanation",
        headers=role_headers[0],
    )
    recommendations = client.get(
        "/incidents/incident-a/recommendations",
        headers=role_headers[0],
    )
    cross_tenant = client.get(
        "/incidents/incident-b/mitigation",
        headers=role_headers[0],
    )

    assert all(response.status_code == 200 for response in responses)
    body = responses[0].json()
    assert body["mitigation_mode"] == "threat_specific"
    assert explanation.status_code == 200
    assert explanation.json()["mitigation_mode"] == "threat_specific"
    assert explanation.json()["matched_threats"][0]["match_confidence"] == "HIGH"
    assert "observed" in explanation.json()["match_basis"]
    assert recommendations.status_code == 200
    assert any("identity audit record" in item["check"] for item in recommendations.json())
    assert set(body["mitigation"]) == {"immediate", "short_term", "hardening"}
    assert body["mitigation"]["immediate"][0]["provider_specific"] is True
    assert body["is_retrospective"] is True
    assert body["post_incident_review"]["promoted_phase"] == "hardening"
    assert body["post_incident_review"]["resolution_record"] == {
        "type": "contained",
        "who": "operator-a",
        "when": now.isoformat(),
        "note": "Credential review completed.",
    }
    assert cross_tenant.status_code == 404

    with factory.session_scope() as session:
        incident_after = session.get(IncidentRow, "incident-a")
        row_after = session.get(RcaCaseRow, "rca-a")
        assert incident_after.details == before_incident_details
        assert row_after.body == before_rca_body
