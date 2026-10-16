"""Contracts for data-driven synthetic cloud threat scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class MetricSignature:
    metric_family: str
    direction: str
    magnitude: float
    shape: str
    duration_minutes: int


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    display_name: str
    description: str
    category: str
    providers: List[str]
    entity_types: List[str]
    signature: List[MetricSignature]
    intensity_presets: dict[str, float]
    seed: int
    minimum_severity: str


__all__ = ["MetricSignature", "ScenarioSpec"]
