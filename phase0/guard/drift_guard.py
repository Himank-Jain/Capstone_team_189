"""
phase0/guard/drift_guard.py
===========================
Drift guard for the adaptive rolling baseline (Invention A).

A rolling baseline that learns from every reading can be walked away from
normal by a slow, steady change (a "boiling frog" attack). The guard keeps a
validated snapshot of each bucket and measures how far the live baseline has
moved from it.

Per bucket k the normalised shift is  x_k = (b_k - b_snap_k) / s_snap_k,
where b_k is the bucket's window median and s_snap_k the robust scale
(1.4826 * MAD, floored) of the snapshot window. The entity's drift is the
*coherent* shift across all its buckets:

    D(t) = | median_k x_k(t) |

An attack shifts every bucket the same way; ordinary sampling wander moves
single buckets independently and cancels in the median. Two views are bounded:

* windowed   - |D(t) - D(t - window_days)|
* cumulative - D(t)

When folding a reading in would push either view past its bound, the reading
is *held*: it is kept out of the baseline and routed to a shadow window, and
one incident is raised for the entity. A held entity is promoted (the shadow
becomes the baseline and is re-snapshotted) only if the shadow is stable and
either enough cohort neighbours moved the same way or an operator approves.
Otherwise it stays held: there is no silent restore.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, Hashable, List, Optional, Sequence, Tuple

MAD_TO_SIGMA = 1.4826
SCALE_FLOOR_FRACTION_OF_STD = 0.5


class GuardAction(str, Enum):
    UPDATE = "update"
    HOLD = "hold"


@dataclass(frozen=True)
class GuardConfig:
    window_days: int = 14
    default_windowed_bound: float = 1.0
    default_cumulative_bound: float = 2.0
    shadow_min_days: int = 14
    shadow_stability_sigma: float = 0.25
    cohort_agreement: float = 0.60
    min_snapshot_samples: int = 5
    min_shadow_per_period: int = 5
    max_incident_severity: str = "MEDIUM"
    # Promotion rule: "cohort" (cohort agreement or operator), "corroborated"
    # (a control-plane change event explains the shift, or operator) or "both".
    promotion_rule: str = "cohort"


@dataclass
class GuardDecision:
    action: GuardAction
    d_windowed: float = 0.0
    d_cumulative: float = 0.0
    new_incident: bool = False
    reason: str = ""


@dataclass
class PromotionPlan:
    """What the worker must do to adopt the shadow baseline."""
    bucket_values: Dict[Hashable, List[float]]  # buckets with enough shadow data
    shift_sigma: float  # coherent shadow shift, in scale units
    scales: Dict[Hashable, float]  # old per-bucket scale (to shift the rest)


@dataclass
class _Entity:
    snaps: Dict[Hashable, Tuple[float, float]] = field(default_factory=dict)
    shifts: Dict[Hashable, float] = field(default_factory=dict)
    history: Deque[Tuple[float, float]] = field(default_factory=deque)  # (day, signed D)
    held: bool = False
    incident_open: bool = False
    shadow: List[Tuple[float, Hashable, float, float]] = field(default_factory=list)  # day,bucket,value,shift


def _pstdev(values: Sequence[float]) -> float:
    """Population standard deviation in plain floats (statistics.pstdev
    raises on extreme magnitudes)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return (sum((v - mean) ** 2 for v in values) / n) ** 0.5


def robust_scale(values: Sequence[float]) -> float:
    """1.4826 * MAD, floored at a fraction of the standard deviation so a
    near-constant series does not produce a zero scale."""
    if not values:
        return 1e-9
    med = statistics.median(values)
    mad = statistics.median([abs(v - med) for v in values])
    std = _pstdev(values)
    return max(MAD_TO_SIGMA * mad, SCALE_FLOOR_FRACTION_OF_STD * std, 1e-9)


class DriftGuard:
    """Per-entity guard. Pure state machine: no I/O, no clock."""

    def __init__(self, config: Optional[GuardConfig] = None) -> None:
        self.config = config or GuardConfig()
        self._entities: Dict[Hashable, _Entity] = {}
        self._bounds: Dict[Hashable, Tuple[float, float]] = {}

    # -- configuration ------------------------------------------------------

    def set_bounds(self, entity: Hashable, windowed: float, cumulative: float) -> None:
        self._bounds[entity] = (windowed, cumulative)

    def bounds_for(self, entity: Hashable) -> Tuple[float, float]:
        return self._bounds.get(
            entity,
            (self.config.default_windowed_bound, self.config.default_cumulative_bound),
        )

    # -- snapshot -----------------------------------------------------------

    def take_snapshot(self, entity: Hashable, bucket: Hashable, window: Sequence[float], day: float) -> bool:
        """Record the trusted snapshot of one bucket. False if too little data."""
        if len(window) < self.config.min_snapshot_samples:
            return False
        ent = self._entities.setdefault(entity, _Entity())
        med = statistics.median(window)
        ent.snaps[bucket] = (med, robust_scale(window))
        ent.shifts[bucket] = 0.0
        if not ent.history:
            ent.history.append((day, 0.0))
        return True

    def has_snapshot(self, entity: Hashable, bucket: Hashable) -> bool:
        ent = self._entities.get(entity)
        return bool(ent and bucket in ent.snaps)

    def snapshot_of(self, entity: Hashable, bucket: Hashable) -> Optional[Tuple[float, float]]:
        ent = self._entities.get(entity)
        return ent.snaps.get(bucket) if ent else None

    def is_held(self, entity: Hashable) -> bool:
        ent = self._entities.get(entity)
        return bool(ent and ent.held)

    def held_entities(self) -> List[Hashable]:
        return [e for e, s in self._entities.items() if s.held]

    # -- core ---------------------------------------------------------------

    def signed_drift(self, entity: Hashable, override: Optional[Dict[Hashable, float]] = None) -> float:
        ent = self._entities.get(entity)
        if ent is None or not ent.shifts:
            return 0.0
        if override:
            vals = [override.get(k, v) for k, v in ent.shifts.items()]
        else:
            vals = list(ent.shifts.values())
        return statistics.median(vals)

    def _reference(self, ent: _Entity, day: float) -> float:
        cutoff = day - self.config.window_days
        ref = ent.history[0][1] if ent.history else 0.0
        for hday, hval in ent.history:
            if hday <= cutoff:
                ref = hval
            else:
                break
        return ref

    def evaluate(
        self,
        entity: Hashable,
        bucket: Hashable,
        proposed_median: float,
        value: float,
        day: float,
    ) -> GuardDecision:
        """Decide whether a reading may be folded into the baseline.

        ``proposed_median`` is the bucket's window median after the update.
        A bucket without a snapshot is always allowed to update.
        """
        ent = self._entities.get(entity)
        if ent is None or bucket not in ent.snaps:
            return GuardDecision(GuardAction.UPDATE, reason="no snapshot")

        snap_med, snap_scale = ent.snaps[bucket]
        proposed_shift = (proposed_median - snap_med) / snap_scale
        d_signed = self.signed_drift(entity, {bucket: proposed_shift})
        d_cum = abs(d_signed)
        d_win = abs(d_signed - self._reference(ent, day))
        w_bound, c_bound = self.bounds_for(entity)

        if d_win <= w_bound and d_cum <= c_bound:
            return GuardDecision(GuardAction.UPDATE, d_win, d_cum, reason="within bounds")

        ent.shadow.append((day, bucket, value, (value - snap_med) / snap_scale))
        new_incident = not ent.incident_open
        ent.held = True
        ent.incident_open = True
        return GuardDecision(
            GuardAction.HOLD,
            d_win,
            d_cum,
            new_incident=new_incident,
            reason="bound exceeded: " + ("cumulative" if d_cum > c_bound else "windowed"),
        )

    def residual(self, entity: Hashable, bucket: Hashable, value: float) -> float:
        """Normalised residual of an incoming reading against the snapshot."""
        ent = self._entities.get(entity)
        if ent is None or bucket not in ent.snaps:
            return 0.0
        med, scale = ent.snaps[bucket]
        return (value - med) / scale

    def record_accepted(self, entity: Hashable, bucket: Hashable, median: float, day: float) -> None:
        """Remember an accepted baseline median (updates the entity's drift)."""
        ent = self._entities.get(entity)
        if ent is None or bucket not in ent.snaps:
            return
        snap_med, snap_scale = ent.snaps[bucket]
        ent.shifts[bucket] = (median - snap_med) / snap_scale
        d = statistics.median(ent.shifts.values())
        if ent.history and ent.history[-1][0] == day:
            ent.history[-1] = (day, d)
        else:
            ent.history.append((day, d))
        keep_from = day - 2 * self.config.window_days
        while len(ent.history) > 2 and ent.history[1][0] <= keep_from:
            ent.history.popleft()

    def close_incident(self, entity: Hashable) -> None:
        """Operator acknowledged/resolved the incident for this entity."""
        ent = self._entities.get(entity)
        if ent is not None:
            ent.incident_open = False

    # -- promotion ----------------------------------------------------------

    def shadow_is_stable(self, entity: Hashable, day: float) -> bool:
        """The coherent shadow shift over the last ``shadow_min_days`` differs
        from the previous period by less than the stability threshold."""
        ent = self._entities.get(entity)
        if ent is None or not ent.held:
            return False
        span = self.config.shadow_min_days
        recent = [s for d, _, _, s in ent.shadow if d > day - span]
        prior = [s for d, _, _, s in ent.shadow if day - 2 * span < d <= day - span]
        need = self.config.min_shadow_per_period
        if len(recent) < need or len(prior) < need:
            return False
        return abs(statistics.median(recent) - statistics.median(prior)) < self.config.shadow_stability_sigma

    def try_promote(
        self,
        entity: Hashable,
        day: float,
        cohort_same_direction_fraction: float,
        operator_approved: bool = False,
        corroborated: Optional[bool] = None,
    ) -> Optional[PromotionPlan]:
        """Return a plan to adopt the shadow baseline, or None if the entity
        must stay held."""
        ent = self._entities.get(entity)
        if ent is None or not ent.held or not self.shadow_is_stable(entity, day):
            return None
        cohort_ok = cohort_same_direction_fraction >= self.config.cohort_agreement
        corro_ok = bool(corroborated)
        rule = self.config.promotion_rule
        if rule == "corroborated":
            auto = corro_ok
        elif rule == "both":
            auto = cohort_ok and corro_ok
        else:
            auto = cohort_ok
        if not (operator_approved or auto):
            return None
        span = self.config.shadow_min_days
        recent = [s for d, _, _, s in ent.shadow if d > day - span]
        per_bucket: Dict[Hashable, List[float]] = {}
        for d, b, v, _ in ent.shadow:
            if d > day - 2 * span:
                per_bucket.setdefault(b, []).append(v)
        values = {b: vs[-30:] for b, vs in per_bucket.items() if len(vs) >= self.config.min_snapshot_samples}
        return PromotionPlan(
            bucket_values=values,
            shift_sigma=statistics.median(recent),
            scales={b: s for b, (_, s) in ent.snaps.items()},
        )

    def complete_promotion(self, entity: Hashable) -> None:
        """Called after the worker reseeded the buckets: clear the held state
        so the next snapshot starts from the adopted baseline."""
        self._entities.pop(entity, None)
