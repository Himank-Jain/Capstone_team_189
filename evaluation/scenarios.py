"""
Scenario definitions. All shifts are additive and expressed in units of the
entity's own robust hourly scale (``Entity.hour_scale``).

Timeline (days): 0-29 training, snapshot at 30, 30-89 calibration period,
bounds active from 90, events start at 90 unless stated, run ends at 220.

Scenario parameters were fixed before any results were looked at.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

import numpy as np

import os

SNAPSHOT_DAY = 30
BOUNDS_DAY = 90
EVENT_DAY = 90
END_DAY = 220
DRIFT_DAYS = 30
RAMPS = (30, 60, 90)  # attack ramp durations, days
if os.environ.get("EVAL_PROFILE") == "corestack":
    # Real CoreStack series are at most 100 contiguous days: compressed timeline.
    SNAPSHOT_DAY, BOUNDS_DAY, EVENT_DAY, END_DAY = 30, 60, 60, 100
    DRIFT_DAYS, RAMPS = 10, (10, 20, 30)
if os.environ.get("EVAL_PROFILE") == "corestack90":
    # Resources only present in the 90-day CoreStack extract (never used during development).
    SNAPSHOT_DAY, BOUNDS_DAY, EVENT_DAY, END_DAY = 30, 60, 60, 90
    DRIFT_DAYS, RAMPS = 10, (10, 20)
PROFILES = ("linear", "stepped", "noise_masked")
TARGETS = (4.0, 6.0, 8.0)  # final level above original, in scale units


@dataclass(frozen=True)
class Scenario:
    kind: str  # control | attack | benign | adaptive | poisoned_cal | cohort_attack
    profile: str = ""
    magnitude: float = 0.0
    start: int = EVENT_DAY
    cohort_fraction: float = 0.0  # simulated share of cohort neighbours moving the same way
    temporary: bool = False
    ramp_days: int = DRIFT_DAYS
    seed: int = 0
    payload: float = 0.0  # adaptive attacker: level jumped to after the ramp
    hours: Optional[tuple] = None  # shift only these hours of the day (a business-hours-only attacker)


def shift_curve(sc: Scenario, n_days: int = END_DAY) -> np.ndarray:
    """Per-day shift in scale units (before hour-level noise)."""
    days = np.arange(n_days, dtype=float)
    t = np.clip((days - sc.start) / max(sc.ramp_days, 1), 0.0, 1.0)
    if sc.profile == "stepped":
        steps = 6
        t = np.floor(t * steps) / steps
        t = np.where(days - sc.start >= sc.ramp_days, 1.0, t)
    curve = sc.magnitude * t
    if sc.kind == "adaptive":
        curve = np.where(days >= sc.start + sc.ramp_days, sc.payload, curve)
    if sc.temporary:
        end = sc.start + sc.ramp_days + 5
        curve = np.where(days >= end, 0.0, curve)
    return curve


def frog_factor(sc: Scenario, day: int) -> float:
    """Rubinstein et al. (IMC 2009) boiling-frog schedule: the attacked metric's average level grows by the factor
    ``sc.magnitude`` (g = 1.01, 1.02, 1.05 or 1.15 in the paper) every week from ``sc.start``."""
    return sc.magnitude ** (max(0, day - sc.start + 1) / 7.0)


def apply_scenario(entity, sc: Scenario) -> np.ndarray:
    """Return the entity's series with the scenario's shift added. The shift in
    every hour is ``curve[day] * bucket_scale[hour, daytype]``: a coherent
    shift of the same number of scale units in each bucket."""
    from evaluation.data import SIM_START
    from datetime import timedelta

    out = entity.values.copy()
    if sc.kind in ("control", "greedy"):  # "greedy" is closed-loop and is injected reading by reading inside simulate.run
        return out
    if sc.kind == "frog":  # open-loop multiplicative growth, g per week, after Rubinstein et al.
        for d in range(sc.start, len(out) // 24):
            out[d * 24:(d + 1) * 24] *= frog_factor(sc, d)
        return out
    curve = shift_curve(sc)
    rng = np.random.default_rng(sc.seed)
    for d in range(len(curve)):
        if curve[d] == 0.0:
            continue
        weekend = int((SIM_START + timedelta(days=d)).weekday() >= 5)
        scales = entity.bucket_scale[:, weekend]
        if sc.hours is not None:
            mask = np.zeros(24)
            mask[list(sc.hours)] = 1.0
            scales = scales * mask
        seg = slice(d * 24, (d + 1) * 24)
        out[seg] += curve[d] * scales
        if sc.profile == "noise_masked":
            out[seg] += rng.normal(0.0, 0.5, 24) * scales
    return out


def draw_scenarios(entity_index: int, base_seed: int = 7) -> dict:
    """Deterministic scenario assignment for one entity, shared by every
    strategy so comparisons are paired. Profile, target and ramp length cycle
    through all 27 combinations."""
    rng = random.Random(f"{base_seed}-{entity_index}")
    profile = PROFILES[entity_index % 3]
    target = TARGETS[(entity_index // 3) % 3]
    ramp = RAMPS[(entity_index // 9) % 3]
    attack = Scenario("attack", profile, target, ramp_days=ramp, seed=rng.randrange(10**6))
    benign_mag = rng.uniform(0.5, 4.0)
    cohort_wide = rng.random() < 0.5
    benign = Scenario(
        "benign", "linear", benign_mag, ramp_days=7,
        cohort_fraction=0.9 if cohort_wide else 0.0,
        temporary=(rng.random() < 0.25), seed=rng.randrange(10**6),
    )
    poisoned = Scenario("poisoned_cal", "linear", target, start=35,
                        ramp_days=60 + 30 * (entity_index % 3), seed=rng.randrange(10**6))
    cohort_attack = Scenario("cohort_attack", profile, target, ramp_days=ramp,
                             cohort_fraction=0.9, seed=rng.randrange(10**6))
    return {
        "control": Scenario("control"),
        "attack": attack,
        "benign": benign,
        "poisoned_cal": poisoned,
        "cohort_attack": cohort_attack,
    }


def probe_day(sc: Scenario) -> int:
    """Day at which the stored drift is read: shortly after the ramp ends."""
    return min(sc.start + sc.ramp_days + 5, END_DAY - 1)


def adaptive_attack(ramp_level: float, payload: float, seed: int = 0) -> Scenario:
    """Attacker who knows the guard: ramps to ``ramp_level`` (chosen just
    under the cumulative bound) over the drift period, then runs at
    ``payload`` above the original level."""
    return Scenario("adaptive", "linear", ramp_level, ramp_days=90, payload=payload, seed=seed)
