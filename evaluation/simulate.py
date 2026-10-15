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
    held_end_days: Set[int] = field(default_factory=set)
    cusum_days: Set[int] = field(default_factory=set)
    first_alert_drift: Optional[float] = None  # stored drift (sigma) when the first post-event alert fired
    first_alert_day: Optional[int] = None
    drift_daily: List[float] = field(default_factory=list)  # stored drift (sigma) at the end of each day
    ledger: list = field(default_factory=list)
    max_cusum: float = 0.0  # largest value of the sequential statistic after BOUNDS_DAY (null-calibration runs)
    goal_day: Optional[int] = None  # greedy attacker: first day the stored baseline had moved by the attacker's goal

    def first_alert_after(self, day: int) -> Optional[int]:
        later = [d for d in self.alert_days if d >= day]
        return min(later) if later else None


def _timestamp(day: int, hour: int):
    return SIM_START + timedelta(days=day, hours=hour)


def _drift_stats(store, snapshots) -> float:
    """Coherent drift of the stored baseline: |median over buckets of the
    normalised shift from the day-30 snapshot|."""
    from phase0.guard.drift_guard import coherent_drift

    ds = {}
    for key, (med, scale) in snapshots.items():
        st = store.get_bucket_state(key)
        if st is None or not st.window:
            continue
        ds[key] = (statistics.median(st.window) - med) / scale
    return abs(float(coherent_drift(ds))) if ds else 0.0


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
    cusum_h: float = CUSUM_H,
    zclip: Optional[float] = None,
    floor: Optional[float] = None,
    guard_config: Optional[GuardConfig] = None,
    corroborated: Optional[bool] = None,
    raw_bounds: Optional[Tuple[float, float]] = None,
) -> RunResult:
    values = series if series is not None else apply_scenario(entity, scenario)
    res = RunResult()
    eid = f"{entity.entity_id}:{METRIC}"

    guard_mode = strategy.startswith("guard")
    gov = strategy in ("guard_gov", "guard_cgov", "guard_full", "guard_dual", "guard_dualprobe")  # calibrated bounds + CUSUM trigger on the residual vs the trusted snapshot
    gov_x: List[float] = []
    gov_ref: List[float] = []
    gov_mu = gov_sd = None
    gs_pos = gs_neg = 0.0
    probe = strategy in ("guard_probe", "guard_dualprobe")
    fixed_bound = float(strategy.split("guard_b")[1]) if strategy.startswith("guard_b") else None
    window = 90 if strategy == "longwin" else 30
    guard = DriftGuard(guard_config or GuardConfig()) if guard_mode else None
    worker, store = _make_worker(window, guard)
    if guard is not None:
        guard.set_bounds(eid, 1e9, 1e9)  # inactive until bounds are set at BOUNDS_DAY

    snapshots: Dict = {}
    s_pos = s_neg = 0.0
    cusum_day_x: List[float] = []
    cusum_ref: List[float] = []
    checkpoints: List[Tuple[int, dict]] = []
    traces = {"d_w": [], "d_c": [], "signed": [], "day": []}

    greedy = scenario.kind == "greedy"  # Kloft & Laskov style edge-of-acceptance attacker (closed loop)
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
                _install_bounds(guard, eid, strategy, traces, res, validate_calibration, cohort_stats, default_bounds, margin, floor, raw_bounds)
                if strategy in ("guard_cgov", "guard_full", "guard_dual"):  # the sequential detector is the only trigger; bounds only size the ledger step
                    guard.set_ledger_unit(eid, res.bounds[1])
                    if strategy != "guard_dual":  # dual keeps the calibrated bounds as a second trigger
                        guard.set_bounds(eid, 1e9, 1e9)

        if strategy == "rollback" and day % 7 == 0:
            checkpoints.append((day, store.copy_states()))
            checkpoints = checkpoints[-6:]

        for hour in range(24):
            v = float(values[day * 24 + hour])
            ts = _timestamp(day, hour)
            if greedy and day >= scenario.start and res.goal_day is None:
                # the attacker adds load so that each reading sits just inside the acceptance region of the deployed
                # detector (z just under the threshold), which is the greedy optimum against a centroid-style update
                st_g = store.get_bucket_state(BucketKeyResolver().resolve(entity.entity_id, METRIC, ts))
                if st_g is not None and st_g.count >= 5 and st_g.std > 0:
                    v = max(v, st_g.mean + scenario.magnitude * st_g.std)
            point = MetricPoint(entity.entity_id, METRIC, ts, v)

            if strategy in ("adaptive", "longwin", "cusum", "cusum_r", "rollback") or guard_mode:
                r = worker.process_point(point)
                if r.guard_held:
                    res.hold_days.add(day)
                if r.guard_incident:
                    res.incident_days.add(day)
                if gov and day >= SNAPSHOT_DAY:
                    kk = BucketKeyResolver().resolve(point.vm_id, point.metric_name, ts)
                    if guard.has_snapshot(eid, kk):
                        gov_x.append(guard.residual(eid, kk, v))
                if guard_mode and r.guard_evaluated:
                    if BOUNDS_DAY > day >= SNAPSHOT_DAY:
                        traces["d_w"].append(r.guard_d_windowed)
                        traces["d_c"].append(r.guard_d_cumulative)
                        traces["day"].append(day)
                        key_ = BucketKeyResolver().resolve(point.vm_id, point.metric_name, ts)
                        traces["signed"].append(guard.residual(eid, key_, v))
                    if probe and day >= SNAPSHOT_DAY:
                        traces.setdefault("all_day", []).append(day)
                        traces.setdefault("all_dc", []).append(r.guard_d_cumulative)
                        traces.setdefault("all_dw", []).append(r.guard_d_windowed)
                    if probe and day >= BOUNDS_DAY:
                        traces["later_w"] = max(traces.get("later_w", 0.0), r.guard_d_windowed)
                        traces["later_c"] = max(traces.get("later_c", 0.0), r.guard_d_cumulative)
            elif strategy in ("frozen", "clip"):
                r = _manual_step(worker, store, point, strategy, snapshots, day)
            else:
                raise ValueError(strategy)

            if strategy in ("cusum", "cusum_r") and day >= SNAPSHOT_DAY:
                key = BucketKeyResolver().resolve(point.vm_id, point.metric_name, ts)
                snap = snapshots.get(key)
                if snap is not None:
                    cusum_day_x.append((v - snap[0]) / snap[1])

            if r.is_anomaly and not r.cold_start:
                flags_today += 1

        if strategy in ("cusum", "cusum_r") and cusum_day_x:
            xbar = float(np.mean(cusum_day_x))
            cusum_day_x = []
            if day < BOUNDS_DAY:
                cusum_ref.append(xbar)
            else:
                mu0, sd0 = float(np.mean(cusum_ref)), float(np.std(cusum_ref)) + 1e-9
                zd = (xbar - mu0) / sd0
                if strategy == "cusum_r" and zclip:
                    zd = max(-zclip, min(zclip, zd))
                s_pos = max(0.0, s_pos + zd - CUSUM_K)
                s_neg = max(0.0, s_neg - zd - CUSUM_K)
                if s_pos > cusum_h or s_neg > cusum_h:
                    res.cusum_days.add(day)
                    res.alert_days.add(day)
                    s_pos = s_neg = 0.0

        if gov and gov_x:
            xbar = float(np.mean(gov_x))
            gov_x = []
            if day < BOUNDS_DAY:
                gov_ref.append(xbar)
            else:
                if gov_mu is None:  # reference from the calibration window (same estimators as the CUSUM comparator)
                    ref_ = np.asarray(gov_ref)
                    if strategy in ("guard_full", "guard_dual") and res.calib_checks.get("result") not in ("ok", None):
                        # calibration failed validation (trend or contamination): do not trust its level or spread.
                        # Anchor on the trusted snapshot (residual 0) and take the spread from first differences,
                        # which a slow poisoning ramp does not inflate.
                        gov_mu = 0.0
                        gov_sd = max(float(np.std(np.diff(ref_))) / 1.4142, 0.05) if len(ref_) > 3 else 0.05
                        res.calib_checks["trigger_reference"] = "snapshot-anchored"
                    else:
                        gov_mu = float(np.mean(ref_))
                        gov_sd = max(float(np.std(ref_)), 0.05)
                zd = (xbar - gov_mu) / gov_sd
                if zclip:
                    zd = max(-zclip, min(zclip, zd))
                gs_pos = max(0.0, gs_pos + zd - CUSUM_K)
                gs_neg = max(0.0, gs_neg - zd - CUSUM_K)
                res.max_cusum = max(res.max_cusum, gs_pos, gs_neg)
                if (gs_pos > cusum_h or gs_neg > cusum_h) and not guard.is_held(eid):
                    gs_pos = gs_neg = 0.0
                    new_inc = guard.trip(eid, day_epoch(day))
                    if new_inc is not None:
                        res.cusum_days.add(day)
                        res.hold_days.add(day)
                        if new_inc:
                            res.incident_days.add(day)
                        else:
                            res.collapsed_days.add(day)

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
            n = worker.promote_held(day_epoch(day), scenario.cohort_fraction, operator_approves,
                                        (lambda _e: corroborated) if corroborated is not None else None)
            if n:
                res.promoted_buckets += n
                res.promotion_days.append(day)
                gs_pos = gs_neg = 0.0

        if guard_mode and guard.is_held(eid):
            res.held_end_days.add(day)
        if day >= SNAPSHOT_DAY:
            res.drift_daily.append(_drift_stats(store, snapshots))
            if greedy and res.goal_day is None and day >= scenario.start and res.drift_daily[-1] >= scenario.payload:
                res.goal_day = day

        if res.first_alert_drift is None and day >= scenario.start and day in res.alert_days:
            res.first_alert_drift = _drift_stats(store, snapshots)
            res.first_alert_day = day

        if day == probe_day(scenario):
            res.stored_drift_end = _drift_stats(store, snapshots)

    res.stored_drift_final = _drift_stats(store, snapshots)
    if guard_mode:
        res.ledger = list(guard.ledger)
    if collect_traces or probe:
        res.traces = traces
    return res


def day_epoch(day: int) -> float:
    return _timestamp(day, 0).timestamp() / 86400.0


def _install_bounds(guard, eid, strategy, traces, res, validate, cohort_stats, default_bounds, margin, floor=None, raw_bounds=None):
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
        **({"floor": floor} if floor is not None else {}),
        raw_bounds=raw_bounds,
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
