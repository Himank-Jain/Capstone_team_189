"""Evidence-weighted promotion ledger: caps, evidence allowances, episode continuity."""
from phase0.guard import DriftGuard, GuardAction, GuardConfig
from tests.unit.phase0.test_drift_guard import N_BUCKETS, _hold_for_days, _shift_all, _snap_guard


def _ledger_guard(bound=1.0, **cfg):
    g = _snap_guard(promotion_mode="ledger", **cfg)
    g.set_bounds("e", bound, bound)
    return g


def test_stable_shadow_alone_moves_baseline_by_at_most_base_allowance():
    g = _ledger_guard(bound=1.0)
    _hold_for_days(g, 40, sigma=10.0)
    plan = g.try_promote("e", 40, cohort_same_direction_fraction=0.0)
    assert plan is not None and plan.capped
    assert plan.shift_sigma == 1.0          # allow_base (1.0) x cumulative bound
    assert plan.evidence == ("stable_shadow",)
    assert plan.bucket_values == {}         # the shadow itself is not adopted


def test_each_independent_piece_of_evidence_adds_its_own_allowance():
    g = _ledger_guard(bound=1.0)
    _hold_for_days(g, 40, sigma=10.0)
    cohort = g.try_promote("e", 40, 0.9)
    change = g.try_promote("e", 40, 0.0, corroborated=True)
    both = g.try_promote("e", 40, 0.9, corroborated=True)
    assert (cohort.allowance, change.allowance, both.allowance) == (2.0, 4.0, 5.0)
    assert all(p.capped for p in (cohort, change, both))  # 10 sigma still exceeds every allowance


def test_cohort_agreement_alone_cannot_adopt_a_large_shift():
    # the coordinated-attack case: 90% of peers "agree", shift is large
    g = _ledger_guard(bound=0.8)
    _hold_for_days(g, 40, sigma=8.0)
    plan = g.try_promote("e", 40, 1.0)
    assert plan.capped and abs(plan.shift_sigma) <= 2 * 0.8 + 1e-9


def test_small_shift_is_adopted_in_full_once_stable():
    g = _ledger_guard(bound=3.0)
    _hold_for_days(g, 40, sigma=10.0)
    g._bounds["e"] = (3.0, 20.0)  # allowance 20 sigma > the 10 sigma shift
    plan = g.try_promote("e", 40, 0.0)
    assert plan is not None and not plan.capped and plan.bucket_values


def test_operator_lifts_the_cap_and_is_recorded():
    g = _ledger_guard(bound=0.5)
    _hold_for_days(g, 40, sigma=10.0)
    plan = g.try_promote("e", 40, 0.0, operator_approved=True)
    assert plan is not None and not plan.capped
    assert "operator" in g.ledger[-1]["evidence"]


def test_unstable_shadow_is_never_promoted_even_with_evidence():
    g = _ledger_guard()
    for day in range(1, 40):
        for _ in range(3):
            _shift_all(g, 8.0 + day * 0.5, day)
    assert g.try_promote("e", 40, 1.0, corroborated=True) is None


def test_ledger_records_provenance_of_every_step():
    g = _ledger_guard(bound=1.0)
    _hold_for_days(g, 40, sigma=10.0)
    g.try_promote("e", 40, 0.9, corroborated=True)
    row = g.ledger[-1]
    assert row["entity"] == "e" and row["capped"] is True
    assert row["evidence"] == ["stable_shadow", "cohort", "change_event"]
    assert row["step"] == 5.0 and row["need"] > 5.0


def test_capped_step_keeps_the_episode_open_for_a_later_hold():
    g = _ledger_guard(bound=1.0, episode_gap_days=30)
    _hold_for_days(g, 40, sigma=10.0)
    plan = g.try_promote("e", 40, 0.0)
    g.complete_promotion("e", 40, plan.capped)
    for b in range(N_BUCKETS):
        g.take_snapshot("e", b, [10.0] * 20 + [10.2] * 5, day=40)
    g.set_bounds("e", 1.0, 1.0)
    holds = [d for d in _shift_all(g, 5.0, 45) if d.action is GuardAction.HOLD]
    assert holds and not any(d.new_incident for d in holds)


def test_hold_after_the_gap_is_a_new_incident():
    g = _ledger_guard(bound=1.0, episode_gap_days=30)
    _hold_for_days(g, 40, sigma=10.0)
    plan = g.try_promote("e", 40, 0.0)
    g.complete_promotion("e", 40, plan.capped)
    for b in range(N_BUCKETS):
        g.take_snapshot("e", b, [10.0] * 20 + [10.2] * 5, day=40)
    g.set_bounds("e", 1.0, 1.0)
    holds = [d for d in _shift_all(g, 5.0, 100) if d.action is GuardAction.HOLD]
    assert holds and holds[0].new_incident is True


def test_full_mode_is_unchanged_default():
    assert GuardConfig().promotion_mode == "full"


def test_detector_trip_freezes_the_baseline_and_collects_a_shadow():
    g = _ledger_guard(bound=50.0)           # bound so wide it never trips on its own
    assert g.trip("e", 1.0) is True         # new incident
    assert g.is_held("e")
    d = g.evaluate("e", 0, 10.0, 10.1, day=2)
    assert d.action is GuardAction.HOLD and d.reason == "tripped by detector"
    assert g.trip("e", 3.0) is None         # already held: no second incident


def test_tripped_entity_is_promoted_through_the_ledger_like_any_other_hold():
    g = _ledger_guard(bound=50.0)
    g.trip("e", 1.0)
    for day in range(2, 40):
        for b in range(N_BUCKETS):
            g.evaluate("e", b, 10.0, 12.0, day)
    plan = g.try_promote("e", 40, 0.0)
    assert plan is not None and plan.evidence == ("stable_shadow",)


def test_trip_without_a_snapshot_is_ignored():
    g = DriftGuard(GuardConfig(promotion_mode="ledger"))
    assert g.trip("nobody", 1.0) is None


def test_promotion_step_is_revertible_and_rescorable():
    """A promotion step can be undone and its effect on later readings shown."""
    import random
    from datetime import datetime, timedelta, timezone
    import pytest
    from phase0.baseline.in_memory_store import InMemoryRollingBaselineStore
    from phase0.bucketing.bucket_key_resolver import BucketKeyResolver
    from phase0.scoring.zscore_scorer import ZScoreScorer
    from phase0.seasonality.seasonality_classifier import SeasonalityClassifier
    from phase0.types import MetricPoint
    from phase0.workers.anomaly_scoring_worker import AnomalyScoringWorker
    from tests.unit.phase0.test_drift_guard import _Stub

    rng = random.Random(3)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = InMemoryRollingBaselineStore(window_size=30)
    guard = DriftGuard(GuardConfig(promotion_mode="ledger"))
    w = AnomalyScoringWorker(_Stub(), store, lambda r: None, scorer=ZScoreScorer(min_samples=5),
                             seasonality_classifier=SeasonalityClassifier(non_seasonal_metrics=["cpu"]), guard=guard)
    key = BucketKeyResolver.resolve_global("vm", "cpu")
    day_of = lambda d: (t0 + timedelta(days=d)).timestamp() / 86400.0
    pts = []
    promoted_day = None
    for day in range(130):
        level = 50.0 if day < 30 else 56.0
        if day == 30:
            w.freeze_snapshots(day_of(day))
        p = MetricPoint("vm", "cpu", t0 + timedelta(days=day), level + rng.gauss(0, 1))
        pts.append(p)
        w.process_point(p)
        if day == 30:
            guard.set_bounds("vm:cpu", 2.0, 2.0)
        if day >= 45 and promoted_day is None and w.promote_held(day_of(day), 0.0):
            promoted_day = day
    assert promoted_day is not None
    step = next(r for r in guard.ledger if "restore_id" in r)
    before = store.get_bucket_state(key).mean
    assert w.revert_promotion("vm:cpu", step["restore_id"], day_of(promoted_day + 1))
    after = store.get_bucket_state(key).mean
    assert after < before                       # the baseline moved back toward the trusted level
    assert guard.ledger[-1] == {"entity": "vm:cpu", "day": day_of(promoted_day + 1), "reverted": step["restore_id"]}
    # a reading at the shifted level is anomalous against the pre-step baseline
    # (the restore point is dropped by the revert, so re-score before reverting in real use; here it is gone)
    assert w.rescore("vm:cpu", step["restore_id"], pts[-3:]) == []


def test_rescoring_before_revert_flags_what_the_step_made_normal():
    import random
    from datetime import datetime, timedelta, timezone
    from phase0.baseline.in_memory_store import InMemoryRollingBaselineStore
    from phase0.scoring.zscore_scorer import ZScoreScorer
    from phase0.seasonality.seasonality_classifier import SeasonalityClassifier
    from phase0.types import MetricPoint
    from phase0.workers.anomaly_scoring_worker import AnomalyScoringWorker
    from tests.unit.phase0.test_drift_guard import _Stub

    rng = random.Random(4)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = InMemoryRollingBaselineStore(window_size=30)
    guard = DriftGuard(GuardConfig(promotion_mode="ledger"))
    w = AnomalyScoringWorker(_Stub(), store, lambda r: None, scorer=ZScoreScorer(min_samples=5),
                             seasonality_classifier=SeasonalityClassifier(non_seasonal_metrics=["cpu"]), guard=guard)
    day_of = lambda d: (t0 + timedelta(days=d)).timestamp() / 86400.0
    for day in range(130):
        if day == 30:
            w.freeze_snapshots(day_of(day))
            guard.set_bounds("vm:cpu", 2.0, 2.0)
        w.process_point(MetricPoint("vm", "cpu", t0 + timedelta(days=day), (50.0 if day < 30 else 56.0) + rng.gauss(0, 1)))
        if day >= 45:
            w.promote_held(day_of(day), 0.0)
    step = next(r for r in guard.ledger if "restore_id" in r)
    shifted = [MetricPoint("vm", "cpu", t0 + timedelta(days=131 + i), 56.0 + rng.gauss(0, 0.5)) for i in range(5)]
    scored = w.rescore("vm:cpu", step["restore_id"], shifted)
    assert len(scored) == 5
    # against the baseline before the step the readings are further from normal than against the baseline after it
    from phase0.bucketing.bucket_key_resolver import BucketKeyResolver
    key = BucketKeyResolver.resolve_global("vm", "cpu")
    now = [w._scorer.score("vm", "cpu", key, p.value, store.get_bucket_state(key)) for p in shifted]
    assert sum(r.z_score for r in scored) > sum(r.z_score for r in now) + 1.0
    assert all(r.baseline_mean < n.baseline_mean for r, n in zip(scored, now))


# -- the allowance is derived from the validated bound, and the ledger records the validation outcome ---------------

def _first_step(guard, **kw):
    _hold_for_days(guard, 40, sigma=10.0)
    plan = guard.try_promote("e", 40, 0.0, **kw)
    assert plan is not None
    return plan, guard.ledger[-1]


def test_allowance_is_the_validated_bound_times_the_evidence_multiple_and_the_ledger_says_so():
    g = _ledger_guard(bound=0.7)
    g.set_bound_provenance("e", "entity", "ok")
    plan, entry = _first_step(g)
    assert plan.allowance == 0.7 * 1.0 and abs(entry["step"]) == entry["allowance"] == 0.7
    assert (entry["unit"], entry["unit_source"], entry["validation"], entry["bound_source"]) == (0.7, "validated_bound", "ok", "entity")
    assert entry["allow_multiple"] == 1.0


def test_a_larger_validated_bound_buys_a_proportionally_larger_step():
    small, large = _ledger_guard(bound=0.5), _ledger_guard(bound=2.0)
    for g in (small, large):
        g.set_bound_provenance("e", "entity", "ok")
    assert abs(_first_step(small)[1]["step"]) * 4 == abs(_first_step(large)[1]["step"])


def test_failed_validation_falls_back_to_the_default_bound_and_the_ledger_records_the_failure():
    g = _ledger_guard(bound=0.5)  # the default bound the entity was given
    g.set_bound_provenance("e", "default", "trend in calibration period")
    _, entry = _first_step(g)
    assert entry["unit_source"] == "fallback_bound" and entry["validation"] == "trend in calibration period"
    assert entry["unit"] == 0.5


def test_an_unvalidated_bound_is_recorded_as_such():
    g = _ledger_guard(bound=0.9)
    g.set_bound_provenance("e", "unvalidated", "unvalidated")
    assert _first_step(g)[1]["unit_source"] == "unvalidated_bound"


def test_a_guard_with_no_provenance_says_it_was_never_validated():
    entry = _first_step(_ledger_guard(bound=1.0))[1]
    assert (entry["validation"], entry["bound_source"]) == ("not run", "configured") and entry["unit_source"] == "unvalidated_bound"


def test_a_fixed_unit_replaces_the_link_and_is_recorded():
    g = _ledger_guard(bound=0.5, fixed_unit=2.0)
    g.set_bound_provenance("e", "entity", "ok")
    plan, entry = _first_step(g)
    assert plan.allowance == 2.0 and entry["unit_source"] == "fixed" and entry["unit"] == 2.0


def test_hold_only_mode_has_no_promotion_path():
    g = _snap_guard(promotion_mode="none")
    g.set_bounds("e", 1.0, 1.0)
    _hold_for_days(g, 40, sigma=10.0)
    assert g.try_promote("e", 40, 1.0, operator_approved=True, corroborated=True) is None
    assert g.is_held("e") and not g.ledger
