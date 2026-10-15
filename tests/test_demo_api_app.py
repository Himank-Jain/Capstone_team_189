from fastapi.testclient import TestClient

from phase3.api.app import DEMO_STATE, alerts_by_tenant, app
from phase3.api.routers import _support
from phase3.db.models import TenantMembershipRow, TenantRow, UserRow

client = TestClient(app)


def _tenant_headers(tenant_id: str) -> dict[str, str]:
    user_id = "demo-api-test-user"
    with _support.platform_session_factory.session_scope() as session:
        if session.get(UserRow, user_id) is None:
            session.add(
                UserRow(
                    user_id=user_id,
                    email="demo-api-test@example.test",
                    password_hash="test",
                )
            )
            session.flush()
        if session.get(TenantRow, tenant_id) is None:
            session.add(
                TenantRow(
                    tenant_id=tenant_id,
                    name=tenant_id,
                    source_mode="synthetic",
                )
            )
            session.flush()
        membership = (
            session.query(TenantMembershipRow)
            .filter_by(user_id=user_id, tenant_id=tenant_id)
            .one_or_none()
        )
        if membership is None:
            session.add(
                TenantMembershipRow(
                    membership_id=f"membership-{user_id}-{tenant_id}",
                    user_id=user_id,
                    tenant_id=tenant_id,
                    role="OWNER",
                )
            )
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id}


def test_login_and_tenants_and_summary():
    login_res = client.post(
        "/auth/login",
        json={"email": "demo@capstone189.local", "password": "demo"},
    )
    assert login_res.status_code == 200
    body = login_res.json()
    assert body["access_token"]
    assert body["user"]["role"] == "Admin"
    assert body["user"]["user_id"] == "demo-user"

    tenants_res = client.get("/tenants")
    assert tenants_res.status_code == 200
    tenants = tenants_res.json()
    assert len(tenants) == 5

    summary_res = client.get("/stats/summary", headers={"X-Tenant-Id": "google"})
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["active_alerts"] == summary["active_incidents"]
    authorized_incidents = client.get(
        "/incidents",
        headers={"X-Tenant-Id": "google", "X-User-Id": body["user"]["user_id"]},
    )
    assert authorized_incidents.status_code == 200


def test_demo_control_endpoints():
    DEMO_STATE.clear()
    alerts_by_tenant.clear()

    attack_res = client.post(
        "/demo/generate/attack",
        headers=_tenant_headers("google"),
        json={"tenant_id": "google", "scenario": "credential_theft"},
    )
    assert attack_res.status_code == 200
    attack_body = attack_res.json()
    assert attack_body["status"] == "accepted"
    assert "scenario" not in attack_body
    assert "credential_theft" not in str(attack_body)


def test_demo_email_uses_configured_recipient(monkeypatch):
    DEMO_STATE.clear()
    alerts_by_tenant.clear()

    monkeypatch.setenv("DEMO_EMAIL_RECIPIENT", "demo.recipient@example.com")

    email_res = client.post(
        "/demo/generate/alert",
        headers=_tenant_headers("google"),
        json={
            "tenant_id": "google",
            "scenario": "insider_threat",
            "notify_method": "EMAIL",
            "mode": "attack",
        },
    )

    assert email_res.status_code == 200
    body = email_res.json()
    assert body["notify_method"] == "EMAIL"
    assert body["notification"]["email_to"] == "demo.recipient@example.com"


def test_demo_email_uses_tenant_default_recipient_when_available():
    DEMO_STATE.clear()
    alerts_by_tenant.clear()

    email_res = client.post(
        "/demo/generate/alert",
        headers=_tenant_headers("microsoft"),
        json={
            "tenant_id": "microsoft",
            "scenario": "insider_threat",
            "notify_method": "EMAIL",
            "mode": "attack",
        },
    )

    assert email_res.status_code == 200
    body = email_res.json()
    assert body["notify_method"] == "EMAIL"
    assert body["notification"]["email_to"] == "security@microsoft-demo.internal"


def test_repeated_attack_increases_demo_score():
    DEMO_STATE.clear()
    alerts_by_tenant.clear()

    first_res = client.post(
        "/demo/generate/alert",
        headers=_tenant_headers("amazon"),
        json={
            "tenant_id": "amazon",
            "scenario": "insider_threat",
            "notify_method": "PAGE",
            "mode": "attack",
        },
    )
    second_res = client.post(
        "/demo/generate/alert",
        headers=_tenant_headers("amazon"),
        json={
            "tenant_id": "amazon",
            "scenario": "insider_threat",
            "notify_method": "PAGE",
            "mode": "attack",
        },
    )

    assert first_res.status_code == 200
    assert second_res.status_code == 200

    first_body = first_res.json()
    second_body = second_res.json()

    assert "case_evidence" not in first_body["alert_payload"]
    assert all(
        feature.count(":") == 1
        for feature in first_body["alert_payload"]["contributing_features"]
    )
    assert second_body["alert_payload"]["history_context"]["recent_alert_count"] >= 1
    assert second_body["alert_payload"]["contributing_features"]


def test_phase3_demo_flow_covers_unknown_and_confident_rca(monkeypatch):
    from phase3.api.routers._support import (
        hypothesis_engine,
        rca_cases,
        rca_explanations,
        rca_recommendations,
    )
    from phase3.rca.types import CandidateCause

    DEMO_STATE.clear()
    alerts_by_tenant.clear()
    rca_cases.clear()
    rca_explanations.clear()
    rca_recommendations.clear()

    with monkeypatch.context() as patcher:
        patcher.setattr(
            hypothesis_engine,
            "generate",
            lambda _case: [
                CandidateCause(
                    cause_category="UNKNOWN",
                    confidence="LOW",
                    rule_id="test.unknown",
                    supporting_evidence_keys=[],
                    contradicting_evidence_keys=[],
                )
            ],
        )
        unknown_response = client.post(
            "/demo/generate/alert",
            headers=_tenant_headers("amazon"),
            json={
                "tenant_id": "amazon",
                "scenario": "log_tampering",
                "notify_method": "PAGE",
                "mode": "attack",
            },
        )
    assert unknown_response.status_code == 200
    unknown_body = unknown_response.json()
    unknown_incident_id = unknown_body["alert_payload"]["alert_id"]
    assert unknown_body["phase3"]["candidate_causes"][0]["cause_category"] == "UNKNOWN"
    assert unknown_body["phase3"]["notification_deliveries"][0]["success"] is True
    unknown_explanation = client.get(
        f"/incidents/{unknown_incident_id}/explanation",
        headers=_tenant_headers("amazon"),
    )
    assert unknown_explanation.status_code == 200
    assert unknown_explanation.json()["is_fallback"] is True
    assert unknown_explanation.json()["kb_version"]

    confident_body = None
    for _ in range(6):
        response = client.post(
            "/demo/generate/alert",
            headers=_tenant_headers("amazon"),
            json={
                "tenant_id": "amazon",
                "scenario": "credential_theft",
                "notify_method": "PAGE",
                "mode": "attack",
                "intensity": "high",
            },
        )
        assert response.status_code == 200
        body = response.json()
        if body["phase3"]["candidate_causes"][0]["cause_category"] != "UNKNOWN":
            confident_body = body
            break

    assert confident_body is not None
    confident_incident_id = confident_body["alert_payload"]["alert_id"]
    assert confident_body["phase3"]["confidence"] == "HIGH"
    assert confident_body["phase3"]["explanation"]["sections"]
    assert "credential_theft" not in str(confident_body)
    assert confident_body["phase3"]["explanation"]["cause_category"] != "UNKNOWN"

    explanation = client.get(
        f"/incidents/{confident_incident_id}/explanation",
        headers=_tenant_headers("amazon"),
    )
    recommendations = client.get(
        f"/incidents/{confident_incident_id}/recommendations",
        headers=_tenant_headers("amazon"),
    )
    cross_tenant = client.get(
        f"/incidents/{confident_incident_id}",
        headers=_tenant_headers("google"),
    )
    investigation = client.get(
        f"/incidents/{confident_incident_id}/investigation",
        headers=_tenant_headers("amazon"),
    )

    assert explanation.status_code == 200
    assert explanation.json()["is_fallback"] is False
    assert explanation.json()["sections"]
    evidence_section = next(
        section
        for section in explanation.json()["sections"]
        if section["heading"] == "Evidence for this case"
    )
    assert "final_score=" in evidence_section["body"]
    assert recommendations.status_code == 200
    assert recommendations.json()
    assert investigation.status_code == 200
    assert "scenario" not in investigation.json()["case"]
    assert investigation.json()["explanation"] == explanation.json()
    assert investigation.json()["recommendations"] == recommendations.json()
    assert investigation.json()["notification_deliveries"]
    assert cross_tenant.status_code == 404


def test_phase3_onboarding_persists_and_requires_live_confirmation():
    from phase3.api.routers._support import onboarding_service

    start = client.post(
        "/onboarding",
        headers=_tenant_headers("amazon"),
        json={"tenant_name": "Resumable tenant", "source_mode": "live"},
    )
    assert start.status_code == 200
    session_id = start.json()["session_id"]

    step = client.post(
        f"/onboarding/{session_id}/steps/tenant",
        headers=_tenant_headers("amazon"),
        json={"payload": {"tenant_created": True}},
    )
    assert step.status_code == 200
    onboarding_service._sessions.clear()

    resumed = client.get(f"/onboarding/{session_id}", headers=_tenant_headers("amazon"))
    assert resumed.status_code == 200
    assert resumed.json()["steps"]["tenant"]["tenant_created"] is True

    blocked = client.post(
        f"/onboarding/{session_id}/steps/enable_monitoring",
        headers=_tenant_headers("amazon"),
        json={"payload": {"enabled": True}},
    )
    assert blocked.status_code == 409

    confirmed = client.post(
        f"/onboarding/{session_id}/steps/enable_monitoring",
        headers=_tenant_headers("amazon"),
        json={"payload": {"enabled": True}, "confirm_live": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "complete"


def test_phase3_connections_report_channel_readiness_by_tenant():
    response = client.get("/connections", headers=_tenant_headers("google"))

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "google"
    assert body["connections"][0]["provider"] == "GCP"
    channels = {item["channel"]: item["status"] for item in body["notification_channels"]}
    assert channels["PAGE"] == "ready"
    assert channels["SLACK"] == "simulated"
    assert channels["SMS"] == "credentials_required"
    assert channels["WEBHOOK"] == "credentials_required"
    assert channels["PAGERDUTY"] == "credentials_required"


def test_phase3_rca_preserves_attack_specific_features():
    from phase3.api.routers._support import rca_cases

    DEMO_STATE.clear()
    alerts_by_tenant.clear()
    rca_cases.clear()

    response = client.post(
        "/demo/generate/alert",
        headers=_tenant_headers("google"),
        json={
            "tenant_id": "google",
            "scenario": "credential_theft",
            "notify_method": "PAGE",
            "mode": "attack",
        },
    )

    assert response.status_code == 200
    alert_id = response.json()["alert_payload"]["alert_id"]
    case = rca_cases["google"][alert_id]
    assert case.changed_features
    assert all(feature.startswith("metric_family:") for feature in case.changed_features)
