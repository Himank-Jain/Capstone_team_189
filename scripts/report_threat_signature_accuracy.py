"""Evaluate threat signatures against the WP-A synthetic scenario corpus."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from demo_generator.generator import DemoGenerator
from phase3.api.app import app
from phase3.api.routers._support import provision_demo_identity, rca_cases
from phase3.knowledge.threat_signature_matcher import ThreatSignatureMatcher


def main() -> None:
    provision_demo_identity()
    generator = DemoGenerator()
    matcher = ThreatSignatureMatcher()
    rows = []
    scenario_results = []
    top1_hits = 0
    top3_hits = 0

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
            alert_id = response.json()["alert_payload"]["alert_id"]
            rca_case = rca_cases.get(tenant_id, {}).get(alert_id)
            if rca_case is None:
                raise RuntimeError(f"Phase 3 did not persist an RCACase for {alert_id}")

            matches = matcher.match(rca_case)
            if scenario.category == "ambiguous":
                top1_hit = not matches
                top3_hit = not matches
                expected_label = "UNKNOWN (no threat match)"
            else:
                expected_id = scenario.scenario_id
                top1_hit = bool(matches) and matches[0].threat_id == expected_id
                top3_hit = any(match.threat_id == expected_id for match in matches[:3])
                expected_label = f"`{expected_id}`"
            top1_hits += int(top1_hit)
            top3_hits += int(top3_hit)
            ranked = ", ".join(
                f"{match.threat_id} ({match.match_confidence})" for match in matches
            ) or "no threat match"
            scenario_results.append((scenario.scenario_id, ranked, top1_hit, top3_hit))
            rows.append(
                f"| `{scenario.scenario_id}` | {expected_label} | {ranked} | "
                f"{'100%' if top1_hit else '0%'} | "
                f"{'100%' if top3_hit else '0%'} |"
            )

    total = len(generator.scenarios)
    top1_rate = top1_hits / total if total else 0.0
    top3_rate = top3_hits / total if total else 0.0
    report = [
        "# Threat signature accuracy against WP-A synthetic scenarios",
        "",
        f"Evaluated {total} WP-A scenarios through `POST /demo/generate/alert`,",
        "then matched the persisted RCACase. Expected scenario outcomes are used",
        "only by this evaluation script; the matcher receives no scenario ID,",
        "display name, category, or demo label. The deliberately ambiguous",
        "scenario is a correct result only when no threat signature matches.",
        "",
        "This is synthetic-corpus agreement, not an out-of-sample accuracy claim.",
        "Signatures were authored from the stated threat behaviors and existing",
        "metric-family evidence, not tuned to these evaluation outcomes. Unmapped",
        "families remain absent rather than being assigned proxy metrics.",
        "",
        f"- Top-1: {top1_hits}/{total} ({top1_rate:.1%})",
        f"- Top-3: {top3_hits}/{total} ({top3_rate:.1%})",
        "",
        "| WP-A scenario (evaluation only) | Expected outcome | Ranked matches | "
        "Top-1 rate | Top-3 rate |",
        "|---|---|---|---:|---:|",
        *rows,
        "",
        f"Generated at {datetime.now().astimezone().isoformat(timespec='seconds')}.",
        "",
    ]
    output = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "threat_signature_accuracy.md"
    )
    output.write_text("\n".join(report), encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Top-1: {top1_hits}/{total} ({top1_rate:.1%})")
    print(f"Top-3: {top3_hits}/{total} ({top3_rate:.1%})")
    for scenario_id, ranked, top1_hit, top3_hit in scenario_results:
        top1_scenario = "100%" if top1_hit else "0%"
        top3_scenario = "100%" if top3_hit else "0%"
        print(
            f"{scenario_id}: top-1={top1_scenario}, top-3={top3_scenario}; "
            f"matches={ranked}"
        )


if __name__ == "__main__":
    main()
