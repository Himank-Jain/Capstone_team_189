from pathlib import Path

import yaml

from demo_generator.generator import DemoGenerator

VERIFIED_MITRE_NAMES = {
    "T1078.004": "Cloud Accounts",
    "T1098": "Account Manipulation",
    "T1110": "Brute Force",
    "T1485": "Data Destruction",
    "T1486": "Data Encrypted for Impact",
    "T1496": "Resource Hijacking",
    "T1498": "Network Denial of Service",
    "T1530": "Data from Cloud Storage",
    "T1537": "Transfer Data to Cloud Account",
    "T1567": "Exfiltration Over Web Service",
    "T1578": "Modify Cloud Compute Infrastructure",
    "T1580": "Cloud Infrastructure Discovery",
}


def test_signature_and_scenario_catalog_have_complete_threat_knowledge():
    root = Path(__file__).resolve().parents[4]
    knowledge = yaml.safe_load(
        (root / "phase3" / "knowledge" / "knowledge_base.yaml").read_text(
            encoding="utf-8"
        )
    )
    signatures = yaml.safe_load(
        (root / "phase3" / "knowledge" / "threat_signatures.yaml").read_text(
            encoding="utf-8"
        )
    )["signatures"]
    rules = yaml.safe_load(
        (root / "phase3" / "rca" / "hypothesis_rules.yaml").read_text(
            encoding="utf-8"
        )
    )["rules"]
    threats = knowledge["threats"]
    signature_ids = {signature["threat_id"] for signature in signatures}
    cause_ids = {cause["cause_category"] for cause in knowledge["causes"]}

    assert knowledge["kb_version"] == "2.1.0"
    assert {scenario_id for scenario_id in DemoGenerator().scenarios} <= threats.keys()
    assert signature_ids <= threats.keys()
    assert {rule["cause_category"] for rule in rules} <= cause_ids
    public_ids = {threat["public_id"] for threat in threats.values()}
    assert len(public_ids) == len(threats)
    assert public_ids.isdisjoint(DemoGenerator().scenarios)

    required_threat_fields = {
        "public_id",
        "title",
        "definition",
        "how_it_shows_up",
        "typical_stages",
        "mitre_attack",
        "indicators_in_this_case",
        "investigative_checks",
        "mitigation",
        "false_positive_notes",
        "resolution_criteria",
        "limitations",
        "further_reading",
    }
    for threat_id, threat in threats.items():
        assert required_threat_fields <= threat.keys(), threat_id
        for phase in ("immediate", "short_term", "hardening"):
            assert threat["mitigation"][phase], (threat_id, phase)
            assert all(step.get("generic", "").strip() for step in threat["mitigation"][phase])
        assert all(
            {"check", "why", "expected_result", "risk"} <= check.keys()
            for check in threat["investigative_checks"]
        )
        assert all(
            {"id", "name", "url"} <= technique.keys()
            and technique["url"].startswith("https://attack.mitre.org/techniques/")
            and VERIFIED_MITRE_NAMES.get(technique["id"]) == technique["name"]
            for technique in threat["mitre_attack"]
        )
        assert all(
            {"title", "url"} <= item.keys()
            and item["url"].startswith("https://")
            for item in threat["further_reading"]
        )
