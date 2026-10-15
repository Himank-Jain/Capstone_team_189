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
