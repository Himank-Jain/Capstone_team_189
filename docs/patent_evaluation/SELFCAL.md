# A rule for the displacement bound that needs no per-dataset tuning

Status: designed and checked on development data, frozen (commit `2af0fca`), then run once on 336 series from 158 resources
never used before ("fresh2", pre-registered in `PREREG_FRESH2.md`). The fresh2 result is in the last section and is mixed.

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
  rose to 15%. The cohort cross-check and cap (dependent feature D2b in `CLAIMS.md`) therefore apply to the tuned form only.
* A sequential-trigger threshold calibrated the same way is too permissive (14%): real telemetry is more autocorrelated than
  resampled days. It stays a tuned, optional dependent (D5 in `CLAIMS.md`); its threshold is **not** portable by this method.
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

## Fresh data (fresh2, run once, pre-registered)

Data: 336 hourly series from 158 CoreStack resources that appear in neither earlier set; 311 clean series (148 resources) and 18
series with a real shift of at least one scale unit (13 resources). New resources from the same customer dump, not a different
deployment. Rates are with 95% intervals from a bootstrap over whole resources. Tuned design = frozen at `9c892e5`. Self-calibrated
design = this file's rule, no threshold tuned on any data. Report files: `final_results_cs_fresh2_0.05B.json`,
`lit_results_cs_fresh2_0.05.json`, and the same without Public IP series (`..._no_Public_IP_Address.json`).

| Design | False alerts | 1σ | 2σ | 3σ | fast 4σ | business-hours 4σ | Poisoned calibration |
|---|---|---|---|---|---|---|---|
| Adaptive baseline (no guard) | 0% (0-0) | 81% (75-86) | 81% (75-86) | 81% (76-86) | 84% (79-88) | 75% (68-81) | 2% (1-4) |
| Tuned bound + hold + ledger | 0% (0-0) | 0% | 0% | 0% | 0% | 0% | 85% (80-89) |
| Tuned dual trigger + ledger | 9% (4-14) | 78% (72-83) | 79% (74-84) | 79% (74-84) | 80% (75-85) | 79% (73-84) | 85% (80-89) |
| Clipped CUSUM (comparator) | 9% (4-14) | 78% (72-83) | 79% (74-84) | 79% (74-84) | 80% (75-85) | 79% (73-84) | 79% (74-84) |
| **Self-calibrated bound + hold + ledger** | **0% (0-1)** | 14% (8-20) | **85% (80-89)** | **85% (80-89)** | **85% (80-89)** | 1% (0-3) | 85% (80-89) |
| Self-calibrated + freeze on hold (`Bf`) | 0% (0-1) | 14% (8-21) | 85% (79-89) | 85% (79-89) | 85% (80-89) | 1% (0-3) | 85% (80-89) |

Without Public IP series (154 clean series, 93 resources): tuned dual trigger false alerts **18% (9-27)**, 2σ and 3σ detection 58%;
self-calibrated **1% (0-2)**, 2σ and 3σ detection **69% (59-77)**, 1σ 28% (17-39), business-hours 3% (1-5); adaptive baseline
detection 62% at 0% false alerts.

**Plain detection does not separate the self-calibrated design from the unguarded adaptive baseline on this data** (85% against
81%; 69% against 62% without Public IP; the intervals overlap). On fresh2 most series have a tiny robust scale, so a ramp of
2σ or more trips an ordinary z-flag on the injected readings. What the guard adds is elsewhere in the tables: a poisoned
calibration is caught in 85% instead of 2%, the attack is absorbed into the stored baseline in 0% instead of 15% of 3σ runs, and
the greedy attacker reaches its goal in 0 of 49 instead of 49 of 49.

Resolution and absorption (fresh2):

| Design | Legitimate growth flagged | ...left unresolved | Real shifts flagged | ...left unresolved | Share of attack absorbed at end (3σ stealth) |
|---|---|---|---|---|---|
| Tuned dual trigger + ledger | 81% | 13% (6-20) | 83% (71-100) | 67% (47-86) | 5% (2-8) |
| Self-calibrated | 66% (60-71) | **99% (97-100)** | 83% (71-100) | 73% (56-92) | 0% (0-1) |
| Self-calibrated + freeze on hold | 66% (59-71) | **99% (97-100)** | 83% (71-100) | 80% (59-100) | 0% (0-1) |

Literature attacks on fresh2 (implemented by us; not third-party data):

* Greedy attacker (Kloft and Laskov), 49 clean series from 19 resources in which it reaches its goal against the adaptive
  baseline: both self-calibrated variants detect 100% (median 18 days), **reach the goal in 0 of 49**, stored displacement at the end
  median 0.39σ (`B`) and 0.34σ (`Bf`), 90th percentile 0.55σ and 0.82σ. The tuned dual trigger also detects 100% (8 days) and none
  reach the goal, but its 90th-percentile stored displacement is 4.1σ. The adaptive baseline never flags it and reaches the goal in
  100%, as does clipped CUSUM (which detects 94%). (On development data the partial hold reached the goal in 56% and the freeze in 12%; this was 0% on fresh2.)
* Boiling frog (Rubinstein et al.): g = 1.01 and 1.02 move no series by one scale unit within 90 days; g = 1.05 qualifies 4
  series; g = 1.15 qualifies 45 series from 19 resources: self-calibrated detects 11% (2-23), the tuned dual trigger and clipped CUSUM 71% (53-86), the
  baseline that clips each update 91% (79-100). Stored displacement at the end is about 0.5σ at the 90th percentile for every strategy, so this
  test does not separate them. The evidence on this attack is thin.

### Against the pre-registered criteria

| Criterion (`PREREG_FRESH2.md`, section 5) | Result | Counts against? |
|---|---|---|
| False alerts above 10% or interval excluding 5% from above | 0% (0-1) | no (conservative: far below target) |
| 2σ and 3σ detection no better than the tuned design at the false-alert rate each reaches | 85% against 79% at 0% against 9% false alerts; 69% against 58% at 1% against 18% without Public IP (the unguarded adaptive baseline detects 81% and 62%) | no |
| Real shifts and legitimate growth left unresolved more often than the tuned design | growth 99% against 13%; real shifts 73% against 67% (intervals overlap) | **yes, for legitimate growth** |
| Greedy attacker reaching its goal in more than 25% | 0% | no |

### What the fresh result does and does not show

* **The bound is the fixed floor for 98% of the clean series** (304 of 311; 157 of 157 Public IP, 48 of 48 bucket series).
  The self-calibration decides the bound for 2% of them, so on this data the low false-alert rate comes from the fixed 0.5σ floor,
  not from the resampling. The tuned design's floor was tuned to 4σ and never trips; the fixed floor does the work. What the rule
  does show is that no per-dataset number was needed to get 0% false alerts here. It does not show that the resampling improves
  on a fixed 0.5σ bound.
* **A 15% ceiling on stealth detection comes from 48 bucket series** (one per resource; GCP `total_byte_seconds`): no strategy,
  including the adaptive baseline's ordinary z-flag and the tuned dual trigger, detects any injected attack on them. The cause was
  not diagnosed. Detection is 100% on the other 263 clean series. These 48 series also contribute zero false alerts.
* **Legitimate growth is the price of the bound.** With the unit at the 0.5σ floor a promotion step moves the baseline by about
  0.5σ per 14 days (`GUARANTEE.md`), so a 2σ change takes at least 42 days to be adopted and only 30 days follow the event in
  these 90-day series. This is the guarantee working as stated and it is also the failure of the criterion above. The operator-set
  allowance multiple would trade this against the bound; it was not changed after seeing fresh2.
* **Small and business-hours attacks go through.** 1σ stealth is detected for 14% and a 4σ attack in business hours only for 1%
  (tuned dual trigger: 78% and 79%). A fleet-wide statistic that needs a coherent shift across hour buckets will not see an
  attacker who touches eight hours.
* **Not third-party attack data.** The only attack strategies are ours or implemented from papers.
* One false alert in 311 series (an app-service plan), so the false-alert rate on this data cannot be distinguished from 0%.
