# Stated bound on how fast promotion can move the stored baseline

Working note for the patent attorney. Not legal advice. It states what is guaranteed by construction, checks it against the code
and against simulated runs, and says what it does **not** give.

## Statement (ledger mode, no operator approval)

Notation: `U` is the ledger unit (the entity's cumulative bound, in scale units); `a0 = allow_base`, `ac = allow_cohort`,
`ae = allow_corroborated` (defaults 1, 1, 3); `S = shadow_min_days` (default 14).

1. **Step bound.** One promotion step moves the live baseline's coherent shift by at most
   `A = (a0 + ac·[cohort evidence] + ae·[change-event evidence]) · U`. With no evidence `A = a0·U`.
   Source: `DriftGuard.try_promote`, ledger branch (`step = ±allowance` whenever `|need| > allowance`).
2. **Spacing.** Two promotion steps of one entity are at least `S` days apart. A promotion needs a stable shadow, which needs at
   least `min_shadow_per_period` shadow readings in each of two consecutive `S`-day windows, and `complete_promotion` clears the
   held state after every step.
3. **Consequences, checkable.**
   * In any window of `W` days the promotion-driven movement is at most `(⌊W/S⌋ + 1) · A_max`.
   * To move the stored baseline by a shift `Δ` through promotion takes at least `⌈Δ/A⌉` steps, so at least
     `(⌈Δ/A⌉ − 1) · S` days between the first and the last step. This is a lower bound on the response window.

## What was checked

`evaluation/guarantee_check.py` (development sets only; stealth 2σ and 3σ, fast 4σ and benign-growth runs of the proposed design):

| Set | Runs | Promotion steps | Largest step / allowance | Steps over allowance | Shortest gap between steps | Gaps under S |
|---|---|---|---|---|---|---|
| NAB dev | 472 | 585 | 1.00 | 0 | 23 days | 0 |
| CoreStack dev | 260 | 130 | 1.00 | 0 | no entity had two steps | 0 |

Unit tests: `tests/unit/phase0/test_drift_guard_ledger.py` (allowance with and without evidence, cap not lifted by cohort
agreement alone, operator lifts the cap and is recorded).

## What this does not give

* **It does not stop a small attack.** The tuned unit is about 4 scale units (median `U` = 4.0 on all four sets) and `a0 = 1`, so
  `A` is about 4σ. A 3σ attack fits inside one step. The bound is real, but at these settings it only limits shifts larger than
  about 4σ per 14 days.
* **A smaller `a0` makes it bite, at a cost.** The step-size sweep (`cap_sweep_nab_dev.json`, development data) shows that
  `a0 = 0.25` (about 1σ per step) leaves the median attack absorption at +14 days unchanged (0.18), cuts it slightly at +30
  days (0.50 against 0.56), and leaves it near 1.0 at +60 days (0.95 against 1.0), while slowing the resolution of legitimate
  growth (hold ended by +30 days: 42% against 65%). In other words the bound can be tightened, and the price is slower
  resolution of real growth.
* **Only promotion is bounded.** Movement in the update state, between holds, is limited only by the triggers (the displacement
  bound and the CUSUM thresholds), plus one day of overshoot. After a promotion the snapshot is reset, so the bound is per
  cycle, not against the original snapshot.
* **Operator approval lifts the cap** by design and is recorded.
* **Unexplained end-to-end exceedances.** The largest rise of the stored displacement over a 14-day window after the first alert
  exceeded two units in 4 of 198 stable runs across the four sets (all four on development sets: two NAB entities, two CoreStack entities with unit 0.5; none on fresh sets). One NAB run
  shows a transient 67σ rise while its final displacement is 2.1σ, which points to a measurement artefact in the drift series
  (scale units change when the snapshot resets), but this has not been investigated. Until it is, the end-to-end rate bound
  should be claimed only for promotion steps, not for the whole displacement series.

## Wording for the specification

"A promotion step changes the live baseline by no more than an allowance determined from the unit and from the evidence
recorded for that step, and two promotion steps for one entity are separated by at least the shadow period; hence the time to
move the live baseline by a given amount through promotion has a stated lower bound." Do not write that attacks cannot move the
baseline.
