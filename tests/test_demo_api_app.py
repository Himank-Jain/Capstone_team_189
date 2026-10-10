from fastapi.testclient import TestClient

from backend.api_demo_ext.app import DEMO_STATE, alerts_by_tenant, app


client = TestClient(app)


def test_login_and_tenants_and_summary():
    login_res = client.post("/auth/login", json={"email": "demo@capstone189.local", "password": "demo"})
    assert login_res.status_code == 200
    body = login_res.json()
    assert body["access_token"]
    assert body["user"]["role"] == "Admin"

    tenants_res = client.get("/tenants")
    assert tenants_res.status_code == 200
    tenants = tenants_res.json()
    assert len(tenants) == 5

    summary_res = client.get("/stats/summary", headers={"X-Tenant-Id": "google"})
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["active_alerts"] == 12


def test_demo_control_endpoints():
    DEMO_STATE.clear()
    alerts_by_tenant.clear()

    attack_res = client.post(
        "/demo/generate/attack",
        json={"tenant_id": "google", "scenario": "credential_theft"},
    )
    assert attack_res.status_code == 200
    attack_body = attack_res.json()
    assert attack_body["status"] == "accepted"
    assert attack_body["scenario"] == "credential_theft"


def test_demo_email_uses_configured_recipient(monkeypatch):
    DEMO_STATE.clear()
    alerts_by_tenant.clear()

    monkeypatch.setenv("DEMO_EMAIL_RECIPIENT", "demo.recipient@example.com")

    email_res = client.post(
        "/demo/generate/alert",
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
        json={
            "tenant_id": "amazon",
            "scenario": "insider_threat",
            "notify_method": "PAGE",
            "mode": "attack",
        },
    )
    second_res = client.post(
        "/demo/generate/alert",
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

    assert second_body["alert_payload"]["final_score"] > first_body["alert_payload"]["final_score"]
    assert second_body["alert_payload"]["history_context"]["same_scenario_count"] >= 1


def test_phase3_demo_flow_covers_unknown_and_confident_rca():
    from backend.api_demo_ext.phase3_routes import (
        rca_cases,
        rca_explanations,
        rca_recommendations,
    )

    DEMO_STATE.clear()
    alerts_by_tenant.clear()
    rca_cases.clear()
    rca_explanations.clear()
    rca_recommendations.clear()

    unknown_response = client.post(
        "/demo/generate/alert",
        json={
            "tenant_id": "amazon",
            "scenario": "credential_theft",
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
        headers={"X-Tenant-Id": "amazon"},
    )
    assert unknown_explanation.status_code == 200
    assert unknown_explanation.json()["is_fallback"] is True
    assert unknown_explanation.json()["kb_version"]

    confident_body = None
    for _ in range(6):
        response = client.post(
            "/demo/generate/alert",
            json={
                "tenant_id": "amazon",
                "scenario": "credential_theft",
                "notify_method": "PAGE",
                "mode": "attack",
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

    explanation = client.get(
        f"/incidents/{confident_incident_id}/explanation",
        headers={"X-Tenant-Id": "amazon"},
    )
    recommendations = client.get(
        f"/incidents/{confident_incident_id}/recommendations",
        headers={"X-Tenant-Id": "amazon"},
    )
    cross_tenant = client.get(
        f"/incidents/{confident_incident_id}",
        headers={"X-Tenant-Id": "google"},
    )

    assert explanation.status_code == 200
    assert explanation.json()["is_fallback"] is False
    assert explanation.json()["sections"]
    evidence_section = next(
        section
        for section in explanation.json()["sections"]
        if section["heading"] == "Evidence for this case"
    )
    assert "suspicious_login_location" in evidence_section["body"]
    assert recommendations.status_code == 200
    assert recommendations.json()
    assert cross_tenant.status_code == 404


def test_phase3_onboarding_persists_and_requires_live_confirmation():
    from backend.api_demo_ext.phase3_routes import onboarding_service

    start = client.post(
        "/onboarding",
        json={"tenant_name": "Resumable tenant", "source_mode": "live"},
    )
    assert start.status_code == 200
    session_id = start.json()["session_id"]

    step = client.post(
        f"/onboarding/{session_id}/steps/tenant",
        json={"payload": {"tenant_created": True}},
    )
    assert step.status_code == 200
    onboarding_service._sessions.clear()

    resumed = client.get(f"/onboarding/{session_id}")
    assert resumed.status_code == 200
    assert resumed.json()["steps"]["tenant"]["tenant_created"] is True

    blocked = client.post(
        f"/onboarding/{session_id}/steps/enable_monitoring",
        json={"payload": {"enabled": True}},
    )
    assert blocked.status_code == 409

    confirmed = client.post(
        f"/onboarding/{session_id}/steps/enable_monitoring",
        json={"payload": {"enabled": True}, "confirm_live": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "complete"


def test_phase3_connections_report_channel_readiness_by_tenant():
    response = client.get("/connections", headers={"X-Tenant-Id": "google"})

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
    from backend.api_demo_ext.phase3_routes import rca_cases

    DEMO_STATE.clear()
    alerts_by_tenant.clear()
    rca_cases.clear()

    response = client.post(
        "/demo/generate/alert",
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
    assert case.changed_features == [
        "iam_policy_change",
        "suspicious_login_location",
        "credential_reset_spike",
    ]
