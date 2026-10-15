"""
evaluation/simulate.py
======================
Runs one entity through one scenario under one baseline strategy.

Strategies
----------
adaptive       production rolling baseline (30-reading window per bucket)
frozen         baseline frozen at the day-30 snapshot
longwin        same as adaptive but a 90-reading window
clip           adaptive, each reading clipped to +/-1 scale unit of the bucket
               median before it is folded in (update clipping)
cusum          adaptive + two-sided CUSUM on z (k=0.5, h=5)
rollback       adaptive + restore a >=14-day-old checkpoint on a z alert
guard_default  adaptive + drift guard, fixed 1.0 / 2.0 scale-unit bounds
guard_naive    guard, per-entity bounds = 1.25 * p99(D) with no validation
guard_cal      guard, per-entity bounds from validated calibration (claimed)

Alert definition (identical for all strategies): a day with at least six
|z|>3 readings, a CUSUM alarm, or a guard incident.
"""

from __future__ import annotations

import copy
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from evaluation.data import SIM_START, Entity
from evaluation.scenarios import (
    BOUNDS_DAY,
    END_DAY,
    SNAPSHOT_DAY,
    Scenario,
    apply_scenario,
    probe_day,
)
from phase0.baseline.in_memory_store import InMemoryRollingBaselineStore
from phase0.bucketing.bucket_key_resolver import BucketKeyResolver
from phase0.guard import DriftGuard, GuardConfig, calibrate_bounds
from phase0.guard.drift_guard import robust_scale
from phase0.scoring.zscore_scorer import ZScoreScorer
from phase0.seasonality.seasonality_classifier import SeasonalityClassifier
from phase0.types import MetricPoint
from phase0.workers.anomaly_scoring_worker import AnomalyScoringWorker

FLAGS_PER_ALERT_DAY = 6
CUSUM_K = 0.5
CUSUM_H = 12.0
CLIP_K = 3.0
ROLLBACK_MIN_AGE_DAYS = 14
METRIC = "m"


class _NoStream:
    def start(self): pass
    def stop(self): pass
    def poll(self, timeout_ms): return []


@dataclass
class RunResult:
    alert_days: Set[int] = field(default_factory=set)
    incident_days: Set[int] = field(default_factory=set)
    hold_days: Set[int] = field(default_factory=set)
    promoted_buckets: int = 0
    promotion_days: List[int] = field(default_factory=list)
    stored_drift_end: float = 0.0  # median over buckets of D_c at day 90
    stored_drift_final: float = 0.0
    bounds: Optional[Tuple[float, float]] = None
    bound_source: str = ""
    calib_checks: dict = field(default_factory=dict)
    traces: Optional[dict] = None
    flag_days: Set[int] = field(default_factory=set)
    collapsed_days: Set[int] = field(default_factory=set)

    def first_alert_after(self, day: int) -> Optional[int]:
        later = [d for d in self.alert_days if d >= day]
        return min(later) if later else None


def _timestamp(day: int, hour: int):
    return SIM_START + timedelta(days=day, hours=hour)


def _drift_stats(store, snapshots) -> float:
    """Coherent drift of the stored baseline: |median over buckets of the
    normalised shift from the day-30 snapshot|."""
    ds = []
    for key, (med, scale) in snapshots.items():
        st = store.get_bucket_state(key)
        if st is None or not st.window:
            continue
        ds.append((statistics.median(st.window) - med) / scale)
    return abs(float(np.median(ds))) if ds else 0.0


def _make_worker(window: int, guard: Optional[DriftGuard]):
    store = InMemoryRollingBaselineStore(window_size=window)
    worker = AnomalyScoringWorker(
        _NoStream(), store, lambda r: None,
        scorer=ZScoreScorer(min_samples=5),
        seasonality_classifier=SeasonalityClassifier(),
        guard=guard,
    )
    return worker, store


def run(
    entity: Entity,
    scenario: Scenario,
    strategy: str,
    bounds: Optional[Tuple[float, float]] = None,
    collect_traces: bool = False,
    series: Optional[np.ndarray] = None,
    validate_calibration: bool = True,
    cohort_stats: Optional[dict] = None,
    operator_approves: bool = False,
    default_bounds: Optional[Tuple[float, float]] = None,
    margin: float = 1.25,
) -> RunResult:
    values = series if series is not None else apply_scenario(entity, scenario)
    res = RunResult()
    eid = f"{entity.entity_id}:{METRIC}"

    guard_mode = strategy.startswith("guard")
    probe = strategy == "guard_probe"
    fixed_bound = float(strategy.split("guard_b")[1]) if strategy.startswith("guard_b") else None
    window = 90 if strategy == "longwin" else 30
    guard = DriftGuard(GuardConfig()) if guard_mode else None
    worker, store = _make_worker(window, guard)
    if guard is not None:
        guard.set_bounds(eid, 1e9, 1e9)  # inactive until bounds are set at BOUNDS_DAY

    snapshots: Dict = {}
    s_pos = s_neg = 0.0
    cusum_day_x: List[float] = []
    cusum_ref: List[float] = []
    checkpoints: List[Tuple[int, dict]] = []
    traces = {"d_w": [], "d_c": [], "signed": [], "day": []}

    for day in range(END_DAY):
        flags_today = 0

        if day == SNAPSHOT_DAY:
            worker.freeze_snapshots(day_epoch(day))
            for key in list(worker._seen_buckets):
                st = store.get_bucket_state(key)
                if st is not None and len(st.window) >= 5:
                    snapshots[key] = (statistics.median(st.window), robust_scale(list(st.window)))

        if guard_mode and day == BOUNDS_DAY:
            if probe:
                pass  # bounds stay open: observe the natural drift, no holds
            elif fixed_bound is not None:
                guard.set_bounds(eid, fixed_bound / 2.0, fixed_bound)
                res.bounds, res.bound_source = (fixed_bound / 2.0, fixed_bound), "fixed"
            else:
                _install_bounds(guard, eid, strategy, traces, res, validate_calibration, cohort_stats, default_bounds, margin)

        if strategy == "rollback" and day % 7 == 0:
            checkpoints.append((day, store.copy_states()))
            checkpoints = checkpoints[-6:]

        for hour in range(24):
            v = float(values[day * 24 + hour])
            ts = _timestamp(day, hour)
            point = MetricPoint(entity.entity_id, METRIC, ts, v)

            if strategy in ("adaptive", "longwin", "cusum", "rollback") or guard_mode:
                r = worker.process_point(point)
                if r.guard_held:
                    res.hold_days.add(day)
                if r.guard_incident:
                    res.incident_days.add(day)
                if guard_mode and r.guard_evaluated:
                    if BOUNDS_DAY > day >= SNAPSHOT_DAY:
                        traces["d_w"].append(r.guard_d_windowed)
                        traces["d_c"].append(r.guard_d_cumulative)
                        traces["day"].append(day)
                        key_ = BucketKeyResolver().resolve(point.vm_id, point.metric_name, ts)
                        traces["signed"].append(guard.residual(eid, key_, v))
                    elif probe and day >= BOUNDS_DAY:
                        traces["later_w"] = max(traces.get("later_w", 0.0), r.guard_d_windowed)
                        traces["later_c"] = max(traces.get("later_c", 0.0), r.guard_d_cumulative)
            elif strategy in ("frozen", "clip"):
                r = _manual_step(worker, store, point, strategy, snapshots, day)
            else:
                raise ValueError(strategy)

            if strategy == "cusum" and day >= SNAPSHOT_DAY:
                key = BucketKeyResolver().resolve(point.vm_id, point.metric_name, ts)
                snap = snapshots.get(key)
                if snap is not None:
                    cusum_day_x.append((v - snap[0]) / snap[1])

            if r.is_anomaly and not r.cold_start:
                flags_today += 1

        if strategy == "cusum" and cusum_day_x:
            xbar = float(np.mean(cusum_day_x))
            cusum_day_x = []
            if day < BOUNDS_DAY:
                cusum_ref.append(xbar)
            else:
                mu0, sd0 = float(np.mean(cusum_ref)), float(np.std(cusum_ref)) + 1e-9
                zd = (xbar - mu0) / sd0
                s_pos = max(0.0, s_pos + zd - CUSUM_K)
                s_neg = max(0.0, s_neg - zd - CUSUM_K)
                if s_pos > CUSUM_H or s_neg > CUSUM_H:
                    res.alert_days.add(day)
                    s_pos = s_neg = 0.0

        if flags_today >= FLAGS_PER_ALERT_DAY and day >= SNAPSHOT_DAY:
            res.flag_days.add(day)
            if guard_mode and day >= BOUNDS_DAY and guard.is_held(eid):
                res.collapsed_days.add(day)  # attaches to the open incident
            else:
                res.alert_days.add(day)
            if strategy == "rollback":
                old = [c for c in checkpoints if day - c[0] >= ROLLBACK_MIN_AGE_DAYS]
                if old:
                    store.restore_states(old[-1][1])

        if guard_mode and not probe and day >= BOUNDS_DAY and res.bounds is not None:
            if res.incident_days and day in res.incident_days:
                res.alert_days.add(day)
            n = worker.promote_held(day_epoch(day), scenario.cohort_fraction, operator_approves)
            if n:
                res.promoted_buckets += n
                res.promotion_days.append(day)

        if day == probe_day(scenario):
            res.stored_drift_end = _drift_stats(store, snapshots)

    res.stored_drift_final = _drift_stats(store, snapshots)
    if collect_traces or probe:
        res.traces = traces
    return res


def day_epoch(day: int) -> float:
    return _timestamp(day, 0).timestamp() / 86400.0


def _install_bounds(guard, eid, strategy, traces, res, validate, cohort_stats, default_bounds, margin):
    dflt = default_bounds or (1.0, 2.0)
    if strategy == "guard_default":
        guard.set_bounds(eid, *dflt)
        res.bounds, res.bound_source = dflt, "default"
        return
    dw, dc = traces["d_w"], traces["d_c"]
    if strategy == "guard_naive" or not validate:
        if len(dc) >= 20:
            w, c = margin * float(np.percentile(dw, 99)), margin * float(np.percentile(dc, 99))
        else:
            w, c = dflt
        guard.set_bounds(eid, w, c)
        res.bounds, res.bound_source = (w, c), "naive"
        return
    alert_flags = None
    if res.flag_days:
        alert_flags = [d in res.flag_days or d in res.incident_days for d in traces["day"]]
    cal = calibrate_bounds(
        dw, dc,
        alert_flags=alert_flags,
        signed_drift=traces["signed"],
        cohort_p95=(cohort_stats or {}).get("p95"),
        cohort_median_bound=(cohort_stats or {}).get("median_bound"),
        default=dflt,
        margin=margin,
    )
    guard.set_bounds(eid, cal.windowed, cal.cumulative)
    res.bounds, res.bound_source, res.calib_checks = (cal.windowed, cal.cumulative), cal.source, cal.checks


def _manual_step(worker, store, point, strategy, snapshots, day):
    key = BucketKeyResolver().resolve(point.vm_id, point.metric_name, point.timestamp)
    state = store.get_bucket_state(key)
    from phase0.types import BucketState
    state = state or BucketState()
    result = worker._scorer.score(point.vm_id, point.metric_name, key, point.value, state)
    worker._seen_buckets.add(key)
    if strategy == "frozen":
        if day < SNAPSHOT_DAY:
            store.update_bucket(key, point.value)
        return result
    # clip
    value = point.value
    if day >= SNAPSHOT_DAY and state.window and key in snapshots:
        med = statistics.median(state.window)
        scale = snapshots[key][1]
        value = min(max(value, med - CLIP_K * scale), med + CLIP_K * scale)
    store.update_bucket(key, value)
    return result
