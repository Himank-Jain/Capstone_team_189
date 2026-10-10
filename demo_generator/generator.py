from dataclasses import dataclass
from typing import Dict, List


@dataclass
class DemoScenario:
    name: str
    description: str
    target_entity_ids: List[str]


class DemoGenerator:
    def __init__(self) -> None:
        self.scenarios = {
            "credential_theft": DemoScenario(
                name="credential_theft",
                description="Burst of unusual auth activity from an unfamiliar region",
                target_entity_ids=["vol-0a12", "vm-01"],
            ),
            "insider_threat": DemoScenario(
                name="insider_threat",
                description="Slow drift with low immediate deviation and rising drift",
                target_entity_ids=["vol-0a12"],
            ),
            "network_scan": DemoScenario(
                name="network_scan",
                description="Rapid-fire Describe* calls across many resources",
                target_entity_ids=["vol-0a12", "vol-0a13", "vol-0a14"],
            ),
        }

    def list_scenarios(self) -> List[Dict[str, str]]:
        return [
            {"name": scenario.name, "description": scenario.description}
            for scenario in self.scenarios.values()
        ]

    def build_payload(self, tenant_id: str, scenario_name: str) -> Dict[str, str]:
        scenario = self.scenarios.get(scenario_name)
        if scenario is None:
            raise ValueError(f"Unknown scenario: {scenario_name}")
        return {
            "tenant_id": tenant_id,
            "scenario": scenario.name,
            "target_entity_ids": ",".join(scenario.target_entity_ids),
        }
