"""Run every scenario through the local API and write an observed-outcome table."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from demo_generator.generator import DemoGenerator
from phase3.api.app import app
from phase3.api.routers._support import provision_demo_identity

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


def main() -> None:
    provision_demo_identity()
    generator = DemoGenerator()
    rows = []
    with TestClient(app) as client:
        for scenario in generator.scenarios.values():
            tenant_id = "amazon"
            headers = {"X-Tenant-Id": tenant_id, "X-User-Id": "demo-user"}
            client.post("/demo/reset", headers=headers).raise_for_status()
            response = client.post(
                "/demo/generate/alert",
                headers=headers,
                json={
                    "tenant_id": tenant_id,
                    "scenario": scenario.scenario_id,
                    "cloud_provider": "AWS",
                    "intensity": "medium",
                    "seed": scenario.seed,
                    "notify_method": "PAGE",
                },
            )
            response.raise_for_status()
            body = response.json()
            actual = body["phase3"]["candidate_causes"][0]["cause_category"]
            severity = body["alert_payload"]["severity"]
            expected = EXPECTED_CAUSES.get(scenario.scenario_id, "—")
            meets_minimum = (
                SEVERITY_RANK[severity] >= SEVERITY_RANK[scenario.minimum_severity]
            )
            rows.append(
                f"| `{scenario.scenario_id}` | {scenario.category.title()} | {expected} | "
                f"{actual} | {severity} | {scenario.minimum_severity} | "
                f"{'Yes' if meets_minimum else 'No'} |"
            )

    report = [
        "# Scenario pipeline outcomes",
        "",
        "Observed by running each data-driven scenario through "
        "`POST /demo/generate/alert` and Phase 3 RCA using the current "
        "`hypothesis_rules.yaml`; scenario IDs and expected categories are "
        "test inputs, not rules or API-result fields.",
        "",
        "| Scenario | Group | Expected cause (test only) | Actual hypothesis | "
        "Severity | Minimum target | Meets target |",
        "|---|---|---|---|---|---|---|",
        *rows,
        "",
        "Cause-category differences are reported, not forced. A severity target "
        "miss is retained in the table and should not be interpreted as a "
        "confirmed threat label.",
        "",
    ]
    output = Path(__file__).resolve().parents[1] / "docs" / "scenario_pipeline_outcomes.md"
    output.write_text("\n".join(report), encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
