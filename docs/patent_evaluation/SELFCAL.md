# A rule for the displacement bound that needs no per-dataset tuning

Status: designed and checked on **development data only** (this file). The fresh2 result is added in the last section
after the pre-registered run (`PREREG_FRESH2.md`).

## The problem

The tuned design set the bound as `m x` the entity's own 99th-percentile calibration drift, with `m` tuned on separate series
(9.92 on NAB, 6.3 on CoreStack), a noise floor tuned to a false-alert target (4 scale units, the top of the grid, i.e. the
target was not reached), and a cohort cap built from the same tuned `m`. Three numbers that differ by dataset cannot be claimed
as a method.

## The rule

At the end of an entity's calibration period, with only its own unlabelled history:

1. Draw 80 clean futures. Each keeps the first 30 training days and then fills every later day with a calibration day of the
   same type (weekday or weekend) drawn with replacement.
2. Run the unmodified baseline on each. Record the largest displacement from the trusted snapshot after the calibration
   period, windowed and cumulative.
3. The bound is the 98.75th percentile (1 - alpha/4 with alpha = 0.05) of each, never below the fixed noise floor of 0.5
   scale units (a constant from the original design: about two standard errors of a 30-reading median).

The operator chooses alpha (the per-entity chance of a false hold over the horizon) and the horizon. Nothing else is chosen.
Everything else in claim 1 (alert exclusion, split-half trend check, default fallback) is unchanged. The default bound used
when validation fails is the median self-calibrated bound of the deployment's own entities.

Code: `evaluation/margin_rule.py` (`selfcal`), `evaluation/selfcal_eval.py`.

## What it was compared with, and what failed

CoreStack development, 65 clean entities from 25 resources, target 5% false alerts. Rates with 95% intervals (bootstrap over
resources).

| Design | False alerts | 1σ stealth | 2σ stealth | 3σ stealth | Poisoned calibration |
|---|---|---|---|---|---|
| Tuned bound + hold + ledger | 8% (2-13) | 14% | 14% | 14% | 98% |
| Tuned dual trigger + ledger (proposed so far) | 8% (2-13) | 63% | 68% | 68% | 98% |
| **Self-calibrated bound + hold + ledger** | **3% (0-7)** | 83% (74-91) | 98% (94-100) | 98% (94-100) | 100% |
| Self-calibrated bound + cohort cap | 15% (6-26) | 85% | 98% | 98% | 100% |
| Self-calibrated bound + sequential trigger | 14% (6-22) | 85% | 100% | 100% | 100% |

* The self-calibrated bound alone meets the false-alert target on real telemetry without any tuning and detects the
  stealth attacks far more often than the tuned design, which had been pushed to the top of its threshold grid.
* The cohort cap from the tuned design must **not** be combined with it: it pulled bounds down to the floor and false alerts
  rose to 15%. The cohort cross-check and cap (dependent claims 4 and 5) therefore apply to the tuned form only.
* A sequential-trigger threshold calibrated the same way is too permissive (14%): real telemetry is more autocorrelated than
  resampled days. It stays a tuned, optional dependent (claim 15); its threshold is **not** portable by this method.
* Early coverage check (95th percentile, 40 futures, with the floor, no cohort): the real future displacement exceeded the
  bound for 4.2% of 72 stable CoreStack entities, against a nominal 5%.

What the bound is made of. For 62% of the clean development entities both self-calibrated bounds fall below the 0.5-scale-unit
floor, so for them the installed bound is the fixed floor, not a number derived from their history. The rule decides the bound for
the other 38%.

Costs seen on development data (same entities): legitimate growth is flagged for 70% of entities and left unresolved for 50%
of those (tuned dual trigger: 63% and 25%); real shifts are flagged for 69% and left unresolved for 65% (tuned: 79% and 70%).
A business-hours-only 4σ attacker is detected for 12% (tuned: 65%), because the bound acts on the coherent shift across buckets.

## Attacks written by others (development data)

Strategies from the literature, implemented by us (`evaluation/lit_attacks.py`). Not third-party data.

* Rubinstein et al. 2009 boiling frog, growth g per week: the self-calibrated design detects 83% of g = 1.02 attacks
  (adaptive baseline 42%, tuned dual trigger 33%) and stores 0.5σ at the end where the adaptive baseline stores 0.65σ to 3.3σ.
* Kloft and Laskov 2012 greedy attacker (readings at z = 2.9 until the stored baseline has moved 6σ): the adaptive baseline
  never flags it and reaches the goal in 100% of entities. The self-calibrated bound with the original partial hold detects
  100% but still lets the attacker reach the goal in 56% (tuned bound: 34%): readings that individually stay inside the bound keep
  entering the window during a hold, and the snapshot is re-taken from that window at the next promotion step. Freezing the
  entity at the first breach (**`Bf`**, now the design under test) reduces this to **12% (5-21)**, median stored displacement
  2.2σ instead of 6.1σ, with no change in false alerts or stealth detection.

## Fresh data

(to be added after the pre-registered run)
