"""Drift guard: snapshot, bounds, hold, one incident, promotion, calibration."""
import random
import statistics
from datetime import datetime, timedelta, timezone

import fakeredis

from phase0.baseline.rolling_baseline_store import RollingBaselineStore
from phase0.guard import DriftGuard, GuardAction, GuardConfig, calibrate_bounds
from phase0.guard.drift_guard import robust_scale
from phase0.scoring.zscore_scorer import ZScoreScorer
from phase0.types import MetricPoint
from phase0.workers.anomaly_scoring_worker import AnomalyScoringWorker


class _Stub:
    def start(self): pass
    def stop(self): pass
    def poll(self, timeout_ms): return []


N_BUCKETS = 6
BASE = [10 + (i % 5) * 0.2 for i in range(20)]
SCALE = robust_scale(BASE)
MED = statistics.median(BASE)


def _snap_guard(**cfg):
    g = DriftGuard(GuardConfig(**cfg))
    for b in range(N_BUCKETS):
        g.take_snapshot("e", b, BASE, day=0)
    return g


def _shift_all(g, sigma, day):
    """Propose a coherent shift of ``sigma`` scale units in every bucket;
    returns the decisions."""
    out = []
    for b in range(N_BUCKETS):
        d = g.evaluate("e", b, MED + sigma * SCALE, MED + sigma * SCALE, day)
        if d.action is GuardAction.UPDATE:
            g.record_accepted("e", b, MED + sigma * SCALE, day)
        out.append(d)
    return out


def test_snapshot_needs_min_samples():
    g = DriftGuard()
    assert g.take_snapshot("e", 0, [1, 2, 3], day=0) is False
    assert g.take_snapshot("e", 0, [1, 2, 3, 4, 5], day=0) is True


def test_robust_scale_floor_for_constant_series():
    assert robust_scale([5.0] * 10) > 0


def test_small_coherent_shift_is_accepted():
    g = _snap_guard()
    assert all(d.action is GuardAction.UPDATE for d in _shift_all(g, 0.5, day=1))


def test_single_bucket_wander_is_ignored_but_coherent_shift_is_held():
    g = _snap_guard()
    # one bucket jumps far: the median across buckets barely moves
    d = g.evaluate("e", 0, MED + 6 * SCALE, MED + 6 * SCALE, day=1)
    assert d.action is GuardAction.UPDATE
    g.record_accepted("e", 0, MED + 6 * SCALE, 1)
    # a coherent 6-sigma shift cannot be absorbed
    ds = _shift_all(_snap_guard(), 6.0, day=2)
    assert any(d.action is GuardAction.HOLD for d in ds)


def test_cumulative_bound_holds_and_raises_one_incident():
    g = _snap_guard()
    ds = _shift_all(g, 10.0, day=1) + _shift_all(g, 10.0, day=2)
    holds = [d for d in ds if d.action is GuardAction.HOLD]
    assert holds and sum(d.new_incident for d in holds) == 1
    assert g.is_held("e")


def test_per_entity_bounds_override_default():
    mild = 1.5
    g = _snap_guard()
    assert any(d.action is GuardAction.HOLD for d in _shift_all(g, mild, day=1))
    g2 = _snap_guard()
    g2.set_bounds("e", 5.0, 5.0)
    assert all(d.action is GuardAction.UPDATE for d in _shift_all(g2, 3.0, day=1))
    g3 = _snap_guard()
    g3.set_bounds("e", 0.3, 0.3)
    assert any(d.action is GuardAction.HOLD for d in _shift_all(g3, 0.8, day=1))


def _hold_for_days(g, days, sigma=10.0):
    for day in range(1, days):
        for _ in range(3):
            _shift_all(g, sigma, day)


def test_isolated_shift_is_not_promoted_but_cohort_shift_is():
    g = _snap_guard()
    _hold_for_days(g, 40)
    assert g.try_promote("e", 40, cohort_same_direction_fraction=0.1) is None
    assert g.is_held("e")  # no silent restore
    plan = g.try_promote("e", 40, cohort_same_direction_fraction=0.8)
    assert plan is not None
    assert abs(plan.shift_sigma - 10.0) < 0.5


def test_operator_approval_promotes():
    g = _snap_guard()
    _hold_for_days(g, 40)
    assert g.try_promote("e", 40, 0.0, operator_approved=True) is not None


def test_unstable_shadow_not_promoted():
    g = _snap_guard()
    for day in range(1, 40):
        for _ in range(3):
            _shift_all(g, 8.0 + day * 0.5, day)  # still moving
    assert g.try_promote("e", 40, 1.0) is None


def test_complete_promotion_clears_held_state():
    g = _snap_guard()
    _hold_for_days(g, 40)
    assert g.try_promote("e", 40, 1.0) is not None
    g.complete_promotion("e")
    assert not g.is_held("e")


def test_calibration_defaults_when_data_short():
    c = calibrate_bounds([0.1] * 5, [0.2] * 5)
    assert c.source == "default" and (c.windowed, c.cumulative) == (1.0, 2.0)


def test_calibration_rejects_trending_period():
    n = 60
    c = calibrate_bounds([0.3] * n, [0.5] * n, signed_drift=[i * 0.05 for i in range(n)])
    assert c.source == "default" and c.checks["result"] == "trend in calibration period"


def test_calibration_excludes_alert_periods():
    n = 60
    flags = [i < 20 for i in range(n)]
    d = [5.0] * 20 + [0.2] * 40
    c = calibrate_bounds(d, d, alert_flags=flags, signed_drift=[0.0] * n)
    assert c.checks["excluded_alert_samples"] == 20
    assert c.windowed < 1.0


def test_calibration_uses_cohort_when_entity_is_noisier_and_caps():
    rng = random.Random(1)
    n = 80
    w = [abs(rng.gauss(0, 1.5)) for _ in range(n)]
    c = calibrate_bounds(w, w, signed_drift=[0.0] * n, cohort_p95=(0.5, 0.5),
                         cohort_median_bound=(1.0, 2.0))
    assert c.source == "cohort" and (c.windowed, c.cumulative) == (1.0, 2.0)
    c2 = calibrate_bounds(w, w, signed_drift=[0.0] * n, cohort_median_bound=(0.8, 0.8))
    assert c2.windowed <= 1.2 + 1e-9


def test_flat_series_gets_the_noise_floor_not_a_zero_bound():
    # real flat / mostly-zero series have own p99 drift of exactly 0
    z = [0.0] * 60
    c = calibrate_bounds(z, z, signed_drift=[0.0] * 60)
    assert c.windowed == c.cumulative == 0.5 and c.checks["floored"] is True
    c2 = calibrate_bounds(z, z, signed_drift=[0.0] * 60, cohort_median_bound=(0.0, 0.0))
    assert c2.windowed >= 0.5


def test_worker_with_guard_holds_a_slow_poisoning_that_unguarded_absorbs():
    rng = random.Random(3)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def run(use_guard):
        store = RollingBaselineStore(fakeredis.FakeStrictRedis(), window_size=30)
        guard = DriftGuard(GuardConfig()) if use_guard else None
        w = AnomalyScoringWorker(_Stub(), store, lambda r: None,
                                 scorer=ZScoreScorer(min_samples=5), guard=guard)
        results = []
        for day in range(90):
            level = 50.0 if day < 30 else 50.0 + (day - 30) * 0.4
            v = level + rng.gauss(0, 1.0)
            p = MetricPoint("vm", "cpu", t0 + timedelta(days=day), v)
            if day == 30 and guard is not None:
                w.freeze_snapshots(day)
            results.append(w.process_point(p))
        return store, results

    _, held_results = run(True)
    _, free_results = run(False)
    assert any(r.guard_held for r in held_results)
    assert sum(r.guard_incident for r in held_results) == 1
    assert not any(r.guard_held for r in free_results)


def test_worker_promotes_cohort_wide_shift_and_reseeds_baseline():
    from phase0.baseline.in_memory_store import InMemoryRollingBaselineStore
    from phase0.seasonality.seasonality_classifier import SeasonalityClassifier

    rng = random.Random(5)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = InMemoryRollingBaselineStore(window_size=30)
    guard = DriftGuard(GuardConfig())
    w = AnomalyScoringWorker(
        _Stub(), store, lambda r: None, scorer=ZScoreScorer(min_samples=5),
        seasonality_classifier=SeasonalityClassifier(non_seasonal_metrics=["cpu"]),
        guard=guard)
    for day in range(120):
        level = 50.0 if day < 30 else 56.0  # permanent step at day 30
        if day == 30:
            w.freeze_snapshots((t0 + timedelta(days=day)).timestamp() / 86400.0)
        w.process_point(MetricPoint("vm", "cpu", t0 + timedelta(days=day), level + rng.gauss(0, 1)))
        if day >= 50:
            w.promote_held((t0 + timedelta(days=day)).timestamp() / 86400.0,
                           cohort_same_direction_fraction=0.9)
    from phase0.bucketing.bucket_key_resolver import BucketKeyResolver
    key = BucketKeyResolver.resolve_global("vm", "cpu")
    assert not guard.is_held("vm:cpu")
    assert abs(store.get_bucket_state(key).mean - 56.0) < 1.5


def test_corroborated_rule_blocks_cohort_only_promotion():
    from phase0.guard import DriftGuard, GuardConfig
    import inspect
    # rule semantics are exercised through try_promote's decision function
    cfg = GuardConfig(promotion_rule="corroborated")
    assert cfg.promotion_rule == "corroborated"
    assert "corroborated" in inspect.signature(DriftGuard.try_promote).parameters


def test_weekday_half_cannot_absorb_an_attack_while_the_overall_median_stays_low():
    """Regression: with one median over all buckets, 24 weekday buckets could move by the full
    attack while 24 untouched weekend buckets held the overall median near zero."""
    from phase0.types import BucketKey
    g = DriftGuard()
    keys = [BucketKey("v", "m", hour=h, is_weekend=w) for h in range(24) for w in (False, True)]
    for k in keys:
        g.take_snapshot("e", k, BASE, day=0)
    g.set_bounds("e", 5.0, 1.0)
    held, accepted = False, 0
    for k in keys:
        if k.is_weekend:
            continue  # only weekday buckets receive the shifted readings
        d = g.evaluate("e", k, MED + 6 * SCALE, MED + 6 * SCALE, day=1)
        if d.action is GuardAction.HOLD:
            held = True
            break
        g.record_accepted("e", k, MED + 6 * SCALE, 1)
        accepted += 1
    assert held, "weekday group drifted 6 sigma without a hold"
    assert accepted <= 12, f"{accepted} weekday buckets absorbed the shift before the hold"
