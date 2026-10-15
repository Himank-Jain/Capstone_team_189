"""
phase3/rca/metric_attribution.py
================================
Deterministic metric attribution (Invention B, step 1).

Turns "this entity's behaviour deviates" into "these named metrics moved,
this far, in this direction" by comparing each metric's observed readings
with that metric's expected level and scale. The result feeds the existing
rule engine (``changed_features`` and ``metric_directions``) so the
explanation stays auditable: same input, same output, no model call.

Expected level and scale come from a *baseline lookup*:

* ``Phase0BaselineLookup`` reads the (drift-guarded) Phase 0 rolling baseline,
  so explanations are computed against the trusted baseline, not against one
  that an attacker has walked away from normal;
* ``ConstantBaselineLookup`` supplies a fixed reference for the synthetic
  demo generator, whose documented baseline level is 100.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from demo_generator.generator import METRIC_FAMILY_KEYWORDS, metric_family_matches
from shared.types import RawRecord

MAD_TO_SIGMA = 1.4826
DEFAULT_THRESHOLD = 3.0  # scale units
PEAK_WINDOW = 3  # readings; the largest short-window median is the "peak" shift
REL_FLOOR = 0.02  # scale is never below 2% of the expected level
ABS_FLOOR = 1e-9

BaselineLookup = Callable[[RawRecord], Optional[Tuple[float, float]]]


@dataclass(frozen=True)
class MetricContribution:
    metric_name: str
    direction: str  # "increase" | "decrease"
    contribution: float  # |observed - expected| / scale
    observed: float
    expected: float
    scale: float
    families: Tuple[str, ...] = ()


@dataclass
class AttributionResult:
    contributions: List[MetricContribution] = field(default_factory=list)
    contributing_features: List[str] = field(default_factory=list)
    metric_directions: Dict[str, str] = field(default_factory=dict)
    unscored_metrics: List[str] = field(default_factory=list)


class ConstantBaselineLookup:
    """Same expected level and scale for every metric (synthetic demo)."""

    def __init__(self, level: float = 100.0, scale: float = 2.0) -> None:
        self._value = (level, scale)

    def __call__(self, record: RawRecord) -> Tuple[float, float]:
        return self._value


class Phase0BaselineLookup:
    """Expected level/scale from a Phase 0 rolling-baseline store."""

    def __init__(self, store, resolver, min_samples: int = 5) -> None:
        self._store = store
        self._resolver = resolver
        self._min_samples = min_samples

    def __call__(self, record: RawRecord) -> Optional[Tuple[float, float]]:
        key = self._resolver.resolve(record.entity_id, record.metric_name, record.timestamp)
        state = self._store.get_bucket_state(key)
        if state is None or len(state.window) < self._min_samples:
            return None
        window = list(state.window)
        med = statistics.median(window)
        mad = statistics.median([abs(x - med) for x in window])
        scale = max(MAD_TO_SIGMA * mad, REL_FLOOR * abs(med), ABS_FLOOR)
        return med, scale


class MetricAttributor:
    def __init__(
        self,
        metric_vocabulary: Sequence[str],
        threshold: float = DEFAULT_THRESHOLD,
        families: Mapping[str, tuple] = METRIC_FAMILY_KEYWORDS,
        peak_window: int = PEAK_WINDOW,
    ) -> None:
        self._threshold = threshold
        self._peak_window = max(1, int(peak_window))
        self._family_of: Dict[str, Tuple[str, ...]] = {}
        vocab = list(metric_vocabulary)
        for family in sorted(families):
            for name in metric_family_matches(family, vocab):
                self._family_of.setdefault(name, ())
                self._family_of[name] = self._family_of[name] + (family,)

    def _peak(self, recs: List[RawRecord], expected: float) -> Tuple[float, float]:
        """Largest deviation of any ``PEAK_WINDOW``-reading median from the
        expected level. Medians keep one stray reading from counting; short
        windows catch steps, ramps and short spikes that a whole-window
        median would average away."""
        values = [r.value for r in recs]
        width = min(self._peak_window, len(values))
        best_obs, best_delta = values[0], values[0] - expected
        for i in range(len(values) - width + 1):
            med = statistics.median(values[i:i + width])
            delta = med - expected
            if abs(delta) > abs(best_delta):
                best_obs, best_delta = med, delta
        return best_obs, best_delta

    def families_of(self, metric_name: str) -> Tuple[str, ...]:
        return self._family_of.get(metric_name, ())

    def attribute(self, observed: Iterable[RawRecord], baseline: BaselineLookup) -> AttributionResult:
        by_metric: Dict[str, List[RawRecord]] = {}
        for rec in observed:
            by_metric.setdefault(rec.metric_name, []).append(rec)

        result = AttributionResult()
        for name in sorted(by_metric):
            recs = by_metric[name]
            ref = baseline(recs[0])
            if ref is None:
                result.unscored_metrics.append(name)
                continue
            expected, scale = ref
            scale = max(scale, REL_FLOOR * abs(expected), ABS_FLOOR)
            obs, delta = self._peak(sorted(recs, key=lambda r: r.timestamp), expected)
            result.contributions.append(
                MetricContribution(
                    metric_name=name,
                    direction="increase" if delta >= 0 else "decrease",
                    contribution=round(abs(delta) / scale, 6),
                    observed=obs, expected=expected, scale=scale,
                    families=self.families_of(name),
                )
            )
        result.contributions.sort(key=lambda c: (-c.contribution, c.metric_name))

        family_best: Dict[str, MetricContribution] = {}
        for c in result.contributions:
            if c.contribution < self._threshold:
                continue
            for family in c.families:
                if family not in family_best:  # contributions are sorted: first is the largest
                    family_best[family] = c
        for family in sorted(family_best, key=lambda f: (-family_best[f].contribution, f)):
            result.contributing_features.append(f"metric_family:{family}")
            result.metric_directions[family] = family_best[family].direction
        return result


__all__ = [
    "AttributionResult",
    "BaselineLookup",
    "ConstantBaselineLookup",
    "MetricAttributor",
    "MetricContribution",
    "Phase0BaselineLookup",
]
