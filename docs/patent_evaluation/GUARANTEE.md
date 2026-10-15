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
| CoreStack dev, self-calibrated design with freeze-on-hold (`envelope_check.py`) | 520 (65 clean entities, 8 scenarios) | 186 | 1.00 | 0 | no entity had two steps | 0 |

Unit tests: `tests/unit/phase0/test_drift_guard_ledger.py` (allowance with and without evidence, cap not lifted by cohort
agreement alone, operator lifts the cap and is recorded).

## What this does not give

* **It does not stop a small attack.** (Tuned design.) The tuned unit is about 4 scale units (median `U` = 4.0 on all four sets) and `a0 = 1`, so
  `A` is about 4σ. A 3σ attack fits inside one step. The bound is real, but at these settings it only limits shifts larger than
  about 4σ per 14 days.
* **Self-calibrated design.** The unit is the installed cumulative bound, which is the fixed 0.5σ floor for the median entity
  (CoreStack dev: median 0.5, 62% of clean entities at the floor), so `A` is about 0.5σ per 14 days and a 3σ shift needs at
  least 6 steps, at least 70 days between the first and the last. This follows from the step bound and was checked on the 186
  steps above. It bounds promotion only (next bullets) and rests on the unit being at the floor for most entities.
* **A smaller `a0` makes it bite, at a cost.** The step-size sweep (`cap_sweep_nab_dev.json`, development data) shows that
  `a0 = 0.25` (about 1σ per step) leaves the median attack absorption at +14 days unchanged (0.18), cuts it slightly at +30
  days (0.50 against 0.56), and leaves it near 1.0 at +60 days (0.95 against 1.0), while slowing the resolution of legitimate
  growth (hold ended by +30 days: 42% against 65%). In other words the bound can be tightened, and the price is slower
  resolution of real growth.
* **Only promotion is bounded.** Movement in the update state, between holds, is limited only by the triggers (the displacement
  bound and the CUSUM thresholds), plus one day of overshoot. After a promotion the snapshot is reset, so the bound is per
  cycle, not against the original snapshot.
* **A hold that withholds only the breaching reading leaks (found on development data).** Readings that individually stay
  inside the bound keep entering the window during a hold, so a greedy attacker (Kloft and Laskov) fills the window below the
  median and the next promotion re-takes the snapshot from it: the stored baseline reached the attacker's 6σ goal in 56% of
  clean CoreStack dev entities (tuned bound: 34%; adaptive baseline: 100%). Freezing the entity at the first breach so that
  every later reading goes to the shadow (`freeze_on_hold`) cut this to 12% (95% interval 5-21%), median stored displacement
  2.2σ against 6.1σ. The 12% that still reach the goal are described in the next bullet.
* **End-to-end envelope check (development data, `evaluation/envelope_check.py`, 65 clean CoreStack entities, self-calibrated
  design with freeze-on-hold).** The statement tested was: after `k` promotion steps the displacement from the day-30 snapshot
  is at most `(k + 1) · bound + Σ step sizes` (each cycle can move up to the bound before the freeze; each step by at most its
  allowance), in the entity's scale units, plus a 0.05σ tolerance. **It does not hold.** Runs with at least one day above the
  envelope: stealth 3σ 0 of 65; boiling frog g = 1.01, 1.02, 1.05: 0 of 65 each (largest ratio 0.99 of the envelope); g = 1.15:
  2 of 65 (largest 1.04); fast 4σ 17 of 65 (11 resources, largest 1.39); benign growth 9 of 65 (7 resources, largest 1.60);
  greedy 25 of 65 (17 resources, largest 2.63). In the worst greedy trace (a near-constant test event-hub series, robust scale
  0.055 units, bound at the 0.5σ floor, one capped step of 0.5σ on day 97) the stored displacement went from 0.93σ to 3.88σ
  on the next day, and the guard recorded no hold on that day. The cause has not been established: the bound acts on the
  coherent (median over buckets) shift and the median of a window of heavily tied values can move by several σ when one
  reading arrives, but this was not isolated. Until it is, **no end-to-end bound is claimed.**
* **Operator approval lifts the cap** by design and is recorded.
* **Earlier unexplained exceedances (tuned design).** The largest rise of the stored displacement over a 14-day window after the
  first alert exceeded two units in 4 of 198 stable runs across the four sets (all four on development sets: two NAB entities,
  two CoreStack entities with unit 0.5; none on fresh sets). One NAB run shows a transient 67σ rise while its final
  displacement is 2.1σ, which points to a measurement artefact in the drift series (scale units change when the snapshot
  resets); not investigated. Together with the envelope check above, the end-to-end rate bound should be claimed only for
  promotion steps, not for the whole displacement series.

## Wording for the specification

"A promotion step changes the live baseline by no more than an allowance determined from the unit and from the evidence
recorded for that step, and two promotion steps for one entity are separated by at least the shadow period; hence the time to
move the live baseline by a given amount through promotion has a stated lower bound." Do not write that attacks cannot move the
baseline.
