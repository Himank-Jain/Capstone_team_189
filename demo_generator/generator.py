"""Load scenario specifications and generate reproducible metric events."""

from __future__ import annotations

import random
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping

import yaml

from demo_generator.types import MetricSignature, ScenarioSpec
from shared.types import RawRecord

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_LIBRARY = Path(__file__).with_name("scenarios") / "library.yaml"
FEATURE_META = PROJECT_ROOT / "model_registry" / "feature_meta.json"
logger = logging.getLogger(__name__)
SUPPORTED_PROVIDERS = ("AWS", "Azure", "GCP", "OCI")
SUPPORTED_INTENSITIES = ("low", "medium", "high")

METRIC_FAMILY_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "api_calls": ("request", "invocation", "serviceapihit", "transactions", "activitysucceeded"),
    "auth_failures": ("failed", "http4xx"),
    "region_activity": (),
    "policy_changes": (),
    "privileged_api_calls": ("request", "serviceapihit", "transactions"),
    "storage_reads": ("read", "volume_read"),
    "network_egress_bytes": ("egress", "networkout", "bytes sent", "bytessent"),
    "cpu_utilization": ("cpu",),
    "unusual_egress": ("egress", "networkout", "bytes sent", "bytessent"),
    "request_count": ("request", "invocation", "serviceapihit", "transactions"),
    "ingress_bytes": ("ingress", "networkin", "bytes received", "bytesreceived"),
    "latency": ("latency", "responsetime", "pickupdelay"),
    "http_5xx": (),
    "storage_write_ops": ("write operations", "writeops", "write_ops", "write operations/sec"),
    "storage_delete_ops": (),
    "object_count": (),
    "anonymous_requests": (),
    "configuration_changes": (),
    "failed_logins": ("failed", "error", "http4xx"),
    "successful_logins": (),
    "east_west_connections": ("inbound flows", "outbound flows", "appconnections"),
    "security_group_changes": (),
    "audit_log_volume": (),
    "resource_create_count": (),
    "serverless_invocations": ("invocation", "functionexecutioncount", "concurrentexecutions"),
    "function_duration": ("duration", "functionexecutionunits"),
    "estimated_cost": (),
    "memory_utilization": ("memory", "mem_used"),
    "disk_write_ops": ("write operations", "writeops", "write_ops"),
    "disk_delete_ops": (),
    "application_requests": ("request", "appconnections", "serviceapihit"),
    "normal_cpu": ("cpu",),
    "normal_requests": ("request", "transactions", "successfulrequests"),
    "normal_storage_writes": ("write operations", "writeops", "write_ops"),
    "regional_error_rate": ("errors", "http4xx", "failed"),
}


def metric_family_matches(metric_family: str, vocabulary: List[str]) -> List[str]:
    """Return only vocabulary entries matching a family's declared keywords."""
    keywords = METRIC_FAMILY_KEYWORDS.get(metric_family, ())
    normalized_names = {name: name.casefold().replace("_", "").replace("-", "") for name in vocabulary}
    normalized_keywords = tuple(
        keyword.casefold().replace("_", "").replace("-", "") for keyword in keywords
    )
    return sorted(
        name
        for name, normalized in normalized_names.items()
        if any(keyword in normalized for keyword in normalized_keywords)
    )


class DemoGenerator:
    """Data-driven synthetic event generator backed by feature metadata."""

    def __init__(
        self,
        library_path: str | Path = SCENARIO_LIBRARY,
        feature_meta_path: str | Path = FEATURE_META,
    ) -> None:
        self._library_path = Path(library_path)
        self._feature_meta_path = Path(feature_meta_path)
        self.metric_vocabulary = self._load_metric_vocabulary()
        self.scenarios = self._load_scenarios()

    def _load_metric_vocabulary(self) -> List[str]:
        import json

        with self._feature_meta_path.open(encoding="utf-8") as handle:
            metadata = json.load(handle)
        vocabulary = metadata.get("vocab_maps", {}).get("metric_name", {})
        if not isinstance(vocabulary, dict) or not vocabulary:
            raise ValueError(f"feature metadata has no metric_name vocabulary: {self._feature_meta_path}")
        return list(vocabulary)

    def _load_feature_clouds(self) -> set[str]:
        import json

        with self._feature_meta_path.open(encoding="utf-8") as handle:
            metadata = json.load(handle)
        vocabulary = metadata.get("vocab_maps", {}).get("cloud", {})
        if not isinstance(vocabulary, dict):
            raise ValueError(f"feature metadata has no cloud vocabulary: {self._feature_meta_path}")
        return set(vocabulary)

    def _load_scenarios(self) -> Dict[str, ScenarioSpec]:
        with self._library_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        rows = data.get("scenarios")
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"scenario library must contain a non-empty scenarios list: {self._library_path}")

        scenarios: Dict[str, ScenarioSpec] = {}
        for row in rows:
            signature = [
                MetricSignature(
                    metric_family=str(item["metric_family"]),
                    direction=str(item["direction"]),
                    magnitude=float(item["magnitude"]),
                    shape=str(item["shape"]),
                    duration_minutes=int(item["duration_minutes"]),
                )
                for item in row["signature"]
            ]
            scenario = ScenarioSpec(
                scenario_id=str(row["scenario_id"]),
                display_name=str(row["display_name"]),
                description=str(row["description"]),
                category=str(row["category"]),
                providers=list(row["providers"]),
                entity_types=list(row["entity_types"]),
                signature=signature,
                intensity_presets={key: float(value) for key, value in row["intensity_presets"].items()},
                seed=int(row["seed"]),
                minimum_severity=str(row["minimum_severity"]),
            )
            self._validate_scenario(scenario)
            if scenario.scenario_id in scenarios:
                raise ValueError(f"duplicate scenario_id in library: {scenario.scenario_id}")
            scenarios[scenario.scenario_id] = scenario
        return scenarios

    def _validate_scenario(self, scenario: ScenarioSpec) -> None:
        if scenario.category not in {"malicious", "benign", "ambiguous"}:
            raise ValueError(f"unsupported scenario category: {scenario.category}")
        if not scenario.signature:
            raise ValueError(f"scenario has no metric signatures: {scenario.scenario_id}")
        if not set(scenario.providers).issubset(SUPPORTED_PROVIDERS):
            raise ValueError(f"scenario has unsupported providers: {scenario.scenario_id}")
        if set(scenario.intensity_presets) != set(SUPPORTED_INTENSITIES):
            raise ValueError(f"scenario must define low/medium/high intensity: {scenario.scenario_id}")
        for item in scenario.signature:
            if item.direction not in {"increase", "decrease"}:
                raise ValueError(f"unsupported signature direction: {item.direction}")
            if item.shape not in {"step", "ramp", "spike"}:
                raise ValueError(f"unsupported signature shape: {item.shape}")
            if item.duration_minutes < 1 or item.magnitude <= 0:
                raise ValueError(f"invalid metric signature in {scenario.scenario_id}")

    def list_scenarios(self) -> List[Dict[str, Any]]:
        return [
            {
                "value": scenario.scenario_id,
                "label": scenario.display_name,
                "description": scenario.description,
                "category": scenario.category,
                "providers": scenario.providers,
                "entity_types": scenario.entity_types,
                "signature": [
                    {
                        "metric_family": item.metric_family,
                        "direction": item.direction,
                        "magnitude": item.magnitude,
                        "shape": item.shape,
                        "duration_minutes": item.duration_minutes,
                    }
                    for item in scenario.signature
                ],
                "minimum_severity": scenario.minimum_severity,
            }
            for scenario in self.scenarios.values()
        ]

    def get_scenario(self, scenario_id: str) -> ScenarioSpec:
        try:
            return self.scenarios[scenario_id]
        except KeyError as exc:
            raise ValueError(f"Unknown scenario: {scenario_id}") from exc

    def build_payload(self, tenant_id: str, scenario_name: str) -> Dict[str, str]:
        scenario = self.get_scenario(scenario_name)
        return {
            "tenant_id": tenant_id,
            "scenario": scenario.scenario_id,
        }

    def generate_events(
        self,
        scenario_id: str,
        cloud_provider: str,
        intensity: str = "medium",
        *,
        entity_id: str = "demo-resource",
        seed: int | None = None,
        start_time: datetime | None = None,
    ) -> List[RawRecord]:
        scenario = self.get_scenario(scenario_id)
        provider = self._canonical_provider(cloud_provider)
        if provider not in scenario.providers:
            raise ValueError(f"{provider} is not enabled for scenario {scenario_id}")
        if intensity not in scenario.intensity_presets:
            raise ValueError(f"unsupported intensity: {intensity}")

        rng = random.Random(scenario.seed if seed is None else seed)
        started = start_time or datetime(2026, 1, 1, tzinfo=timezone.utc)
        entity_type = scenario.entity_types[0]
        namespace = self._namespace(provider, entity_type)
        records: List[RawRecord] = []
        for signature in scenario.signature:
            metric_names = metric_family_matches(signature.metric_family, self.metric_vocabulary)
            if not metric_names:
                logger.warning(
                    "Skipping scenario metric family %s: no matching metric_name in %s",
                    signature.metric_family,
                    self._feature_meta_path,
                )
                continue
            metric_name = rng.choice(metric_names)
            duration = signature.duration_minutes
            intensity_multiplier = scenario.intensity_presets[intensity]
            effective_magnitude = 1.0 + (signature.magnitude - 1.0) * intensity_multiplier
            count = min(duration, 32)
            for step in range(count):
                fraction = (step + 1) / count
                if signature.shape == "step":
                    factor = effective_magnitude if fraction >= 0.5 else 1.0
                elif signature.shape == "ramp":
                    factor = 1.0 + (effective_magnitude - 1.0) * fraction
                else:
                    factor = effective_magnitude if step >= count - min(3, count) else 1.0
                if signature.direction == "decrease":
                    factor = 1.0 / factor
                baseline_value = 100.0
                value = baseline_value * factor * rng.uniform(0.98, 1.02)
                records.append(
                    RawRecord(
                        entity_id=entity_id,
                        timestamp=started + timedelta(minutes=step),
                        cloud=provider,
                        entity_type=entity_type,
                        namespace=namespace,
                        metric_name=metric_name,
                        value=round(value, 6),
                    )
                )
        return records

    @staticmethod
    def _canonical_provider(provider: str) -> str:
        aliases = {"MICROSOFT": "Azure", "GOOGLE": "GCP", "AMAZON": "AWS", "ORACLE": "OCI"}
        canonical = aliases.get(provider.upper(), provider)
        return canonical if canonical in SUPPORTED_PROVIDERS else provider

    @staticmethod
    def _namespace(provider: str, entity_type: str) -> str:
        if provider == "AWS":
            return "AWS/EBS" if entity_type in {"Volumes", "Disks"} else "AWS/EC2"
        if provider == "Azure":
            return (
                "Microsoft.Storage/storageAccounts"
                if entity_type in {"Buckets", "Storage_Accounts"}
                else "Microsoft.Compute/virtualMachines"
            )
        if provider == "GCP":
            return "CWAgent"
        return ""


__all__ = ["DemoGenerator", "METRIC_FAMILY_KEYWORDS", "metric_family_matches"]
