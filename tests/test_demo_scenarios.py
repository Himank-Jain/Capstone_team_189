from datetime import datetime, timezone

from fastapi.testclient import TestClient

from demo_generator.generator import DemoGenerator
from phase3.api.app import DEMO_STATE, _ML_ENTITY_PROFILES, alerts_by_tenant, app
from phase3.api.routers import _support

client = TestClient(app)

EXPECTED_CAUSES = {
    "credential_theft": "BEHAVIOR_CHANGE",
    "insider_threat": "CONFIGURATION_CHANGE",
    "data_exfiltration": "TRAFFIC_CHANGE",
    "malware_execution": "RESOURCE_CHANGE",
    "ddos_volumetric": "TRAFFIC_CHANGE",
    "ransomware": "BEHAVIOR_CHANGE",
    "public_exposure": "CONFIGURATION_CHANGE",
    "brute_force_login": "BEHAVIOR_CHANGE",
    "lateral_movement": "TRAFFIC_CHANGE",
    "log_tampering": "CONFIGURATION_CHANGE",
    "rogue_resources": "RESOURCE_CHANGE",
    "function_abuse": "TRAFFIC_CHANGE",
}

SEVERITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _headers() -> dict[str, str]:
    return {"X-Tenant-Id": "amazon", "X-User-Id": "demo-user"}


def test_scenario_events_are_deterministic_and_use_trained_metric_names():
    generator = DemoGenerator()
    start_time = datetime(2026, 10, 14, tzinfo=timezone.utc)

    for scenario_id, scenario in generator.scenarios.items():
        first = generator.generate_events(
            scenario_id, "AWS", "medium", entity_id="test-resource", start_time=start_time
        )
        second = generator.generate_events(
            scenario_id, "AWS", "medium", entity_id="test-resource", start_time=start_time
        )

        assert first == second
        assert {record.metric_name for record in first}.issubset(
            set(generator.metric_vocabulary)
        )
        assert all(
            record.cloud and record.entity_type and record.namespace is not None
            for record in first
        )
        if scenario_id in {"log_tampering", "public_exposure", "rogue_resources"}:
            assert not first
        else:
            assert first


def test_every_scenario_runs_through_alert_and_phase3_pipeline_without_echoing_label():
    _support.provision_demo_identity()
    DEMO_STATE.clear()
    alerts_by_tenant.pop("amazon", None)
    _support.rca_cases.pop("amazon", None)
    _support.rca_explanations.pop("amazon", None)
    _support.rca_recommendations.pop("amazon", None)
    _ML_ENTITY_PROFILES.pop("vol-amzn", None)
    reset = client.post("/demo/reset", headers=_headers())
    assert reset.status_code == 200

    generator = DemoGenerator()
    below_minimum = []
    observed_categories = {}
    ambiguous_explanation = None
    for scenario_id, scenario in generator.scenarios.items():
        response = client.post(
            "/demo/generate/alert",
            headers=_headers(),
            json={
                "tenant_id": "amazon",
                "scenario": scenario_id,
                "cloud_provider": "AWS",
                "intensity": "medium",
                "seed": scenario.seed,
                "notify_method": "PAGE",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["alert_payload"]["alert_id"]
        assert body["phase3"]["explanation"]
        assert body["phase3"]["recommendations"]
        assert "scenario" not in body
        assert scenario_id.casefold() not in response.text.casefold()

        actual_category = body["phase3"]["candidate_causes"][0]["cause_category"]
        observed_categories[scenario_id] = actual_category
        if scenario_id == "ambiguous_change":
            ambiguous_explanation = body["phase3"]["explanation"]
        minimum = scenario.minimum_severity
        if SEVERITY_RANK[body["alert_payload"]["severity"]] < SEVERITY_RANK[minimum]:
            below_minimum.append(scenario_id)

    assert below_minimum == ["public_exposure", "log_tampering", "rogue_resources"]
    assert set(EXPECTED_CAUSES).issubset(observed_categories)
    assert observed_categories["ambiguous_change"] == "UNKNOWN"
    assert ambiguous_explanation is not None
    assert ambiguous_explanation["is_fallback"] is True
    assert ambiguous_explanation["matched_threats"] == []


def test_demo_injection_requires_matching_tenant_membership():
    _support.provision_demo_identity()
    response = client.post(
        "/demo/generate/alert",
        headers={"X-Tenant-Id": "google", "X-User-Id": "demo-user"},
        json={
            "tenant_id": "amazon",
            "scenario": "credential_theft",
            "cloud_provider": "AWS",
            "intensity": "medium",
        },
    )
    assert response.status_code == 403


def test_malicious_scenarios_get_a_concrete_rca_category():
    """RCA should not fall back to UNKNOWN when the threat signature matched."""
    _support.provision_demo_identity()
    unknown = []
    for scenario in ("credential_theft", "insider_threat", "network_scan", "data_exfiltration"):
        DEMO_STATE.clear()
        alerts_by_tenant.clear()
        response = client.post(
            "/demo/generate/alert",
            headers={"X-Tenant-Id": "google", "X-User-Id": "demo-user"},
            json={"tenant_id": "google", "scenario": scenario, "seed": 7},
        )
        assert response.status_code == 200, response.text
        phase3 = response.json()["phase3"]
        if phase3["explanation"]["mitigation_mode"] == "threat_specific":
            top = phase3["candidate_causes"][0]["cause_category"]
            if top == "UNKNOWN":
                unknown.append(scenario)
            assert top == phase3["explanation"]["cause_category"]
    assert unknown == []
