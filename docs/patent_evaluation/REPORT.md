# Patent evaluation: measured results (frozen-design evaluation)

Everything here is produced by scripts in this repository; the tables are generated into `FINAL_TABLES.md` and `final_summary.json`.
This report **supersedes** the earlier version, whose guard statistic, comparator set and CoreStack status were out of date.
Not legal advice. A desk prior-art search is in `PRIOR_ART.md`; it is not a formal search.

## 1. How the evidence was produced

**Four datasets, two of them never touched before the design was frozen (commit `9c892e5`).**

| Set | What it is | Size | Role |
|---|---|---|---|
| NAB dev | AWS CloudWatch series of the Numenta Anomaly Benchmark, each resampled into 220-day entities from real days (order of days is synthetic) | 151 entities from 14 series; 118 clean | development: thresholds tuned here |
| CoreStack dev | real hourly Azure metrics, 100 contiguous days | 101 series from 32 resources; 65 clean from 25 resources, 29 with real level shifts from 16 resources | development: thresholds tuned here |
| NAB fresh | NAB series from other categories (tweets, ad exchange, known-cause incl. an ASG CPU trace) | 66 entities from 22 series; 26 clean from 11 series | one-shot test |
| CoreStack fresh | resources that exist only in the 90-day extract and were never run before | 53 series from 22 resources; **8 clean from 6 resources**, 41 with real shifts from 16 resources | one-shot test |

n is reported in independent series or resources, not entities. Intervals are 95% from a bootstrap that resamples whole source series.
NAB entities are replicas of a few real series and are labelled *synthetic ordering* throughout.

**Truth labels never come from a detector.** A CoreStack entity is STABLE if no 14-day window of its own data after the event day sits
more than one hour-scale unit from its reference level (`evaluation/stable.py`); the others are real shifts. NAB entities are stationary by
construction apart from injected scenarios. Strategy-specific alerts are isolated on entities where the plain adaptive baseline raises no
ordinary z-flag after the event day. (An earlier report defined "quiet" as "no strategy alerts", which selected against the strategies;
that definition is dropped.)

**Operating point.** One threshold per method, tuned on the development sets only so that stable, ambient-free development entities
false-alert at no more than 5%; frozen in `frozen_design.json`; applied unchanged to the fresh sets. The dual trigger gives each of its
two triggers half the budget. A 10% target was also run on the fresh sets as a secondary point (`final_results_*_0.1.json`).

**Scenarios.** Linear ramps to 1, 2, 3 σ over 60 days (NAB) or 20 days (CoreStack); a 4σ ramp over 10 days; a 4σ shift in 8 business hours
only; poisoned calibration (attacker ramping during the calibration period); sustained legitimate growth of 0.5–4σ with a control-plane
change event at the rate measured on real CoreStack data (20% benign, 6.4% attack). All attacks are team-generated.

**Strategies.** Adaptive baseline, frozen, long window, update clipping (k=3), rollback, CUSUM and a stronger CUSUM with the daily
residual clipped at ±3 (given to the comparators so the comparison is not against a strawman), per-entity calibrated bound guard (with
the old rule and with the ledger), a CUSUM-triggered governor with validated reference, and the proposed dual-trigger design (calibrated
validated bounds + clipped CUSUM, shadow baseline, evidence-weighted capped ledger with restore points), plus ablations.

## 2. Results at the frozen 5% operating point (full tables in `FINAL_TABLES.md`)

Detection of injected attacks and handling of legitimate change, clean entities only. Proposed = dual trigger + validated bounds + ledger.

| | NAB dev | NAB fresh | CoreStack dev |
|---|---|---|---|
| False alerts on clean entities: proposed | 10% (2–21) | 0% (0–0) | 8% (2–13) |
| Clipped CUSUM | 3% (0–5) | 8% (0–24) | 0% (0–0) |
| 2σ stealth detected: proposed / clipped CUSUM / adaptive / rollback | 94% / 92% / 14% / 19% | 100% / 100% / 46% / 50% | 68% / 65% / 57% / 57% |
| 3σ stealth detected: proposed / clipped CUSUM | 96% / 95% | 100% / 100% | 68% / 68% |
| Hour-localised 4σ attacker: proposed / clipped CUSUM / calibrated bound guard | 85% / 90% / 7% | 100% / 100% / 0% | 65% / 62% / 8% |
| Poisoned calibration detected: proposed / clipped CUSUM / adaptive | 100% / 95% / 9% | 100% / 100% / 35% | 98% / 66% / 2% |
| Flagged legitimate growth left unresolved: proposed / clipped CUSUM / frozen | 6% / 84% / 80% | 0% / 83% / 88% | 25% / 69% / 61% |
| Median silent displacement at first alert, 2σ attack (σ): proposed / adaptive / CUSUM | 0.61 / 2.03 / 0.45 | 0.57 / 1.95 / 0.47 | 0.30 / 1.18 / 0.50 |

Reading:
* **Detection** of the proposed design equals the best sequential detector at a matched false-alert rate and is far above the adaptive,
  clipping, long-window and rollback comparators on slow ramps. It is **not better than a clipped CUSUM** on detection.
* **Resolution** is the difference. CUSUM-type and frozen strategies keep alerting after a legitimate shift (61–88% unresolved);
  the proposed design resolves almost all of it on NAB and about 75% on CoreStack dev. The ledger is what resolves: the same design
  without it leaves 100% unresolved (`dual_noledger`).
* **Poisoned calibration** is caught because the bounds are validated before use (validated 21/21 against unvalidated 1/21 on held-out NAB,
  39/39 against 28/39 on CoreStack, from the earlier ablation run). Anchoring the CUSUM reference to the snapshot adds little (66% → 68%).
* **Real shifts in fresh CoreStack** (41 series, 16 resources): the proposed design flags 46% and leaves 58% of those unresolved; clipped
  CUSUM flags 37% and leaves 93%; frozen and rollback leave 100%.
* **Fresh CoreStack clean set is 8 entities from 6 resources**, so its detection and false-alert numbers carry no statistical power
  (the CUSUM-type triggers false-alerted on 2 of 8, against about 3% in development: thresholds tuned on development did not transfer).

## 3. What the ledger does and does not do (absorption after the first alert, 3σ stealth attack)

Median share of the injected shift held in the stored baseline N days after each strategy's own first alert, and the share of flagged
legitimate shifts with no hold or alert in the 14 days from day N.

| | attack +14 d | +30 d | +60 d | legit. resolved +30 d | +60 d |
|---|---|---|---|---|---|
| NAB dev: adaptive | 0.44 | 0.76 | 0.96 | 100% | 100% |
| NAB dev: clipped CUSUM | 0.32 | 0.59 | 0.95 | 18% | 19% |
| NAB dev: rollback | 0.13 | 0.14 | 0.17 | 37% | 44% |
| NAB dev: frozen | 0.00 | 0.00 | 0.00 | 19% | 20% |
| NAB dev: proposed | 0.18 | 0.56 | 1.00 | 88% | 85% |
| NAB fresh: proposed (adaptive / clipped CUSUM) | 0.20 (0.40 / 0.30) | 0.69 (0.70 / 0.56) | 1.04 (0.98 / 0.98) | 91% (100% / 23%) | 86% (100% / 20%) |
| CoreStack dev: proposed (adaptive / clipped CUSUM / frozen) | 0.00 (0.00 / 0.08) | 0.00 (0.57 / 0.88) | – | 81% (100% / 97%) | – |

The statistics cannot separate a persistent attacker level from persistent legitimate growth. The ledger therefore delays the adoption
(on NAB the time until half the shift is in the stored baseline is about 30 days against about 15 for the adaptive baseline; on CoreStack dev the median is still 0 at 30 days) and records it; it does not prevent it. By 60 days
after the first alert the median attacker shift is fully in the stored baseline on NAB. The step-cap sweep (`cap_sweep_*.json`) shows
the cap moves attack and legitimate absorption together, as expected. The earlier "attacker-cost bound" claim is withdrawn.

Reversibility and re-scoring (`AnomalyScoringWorker.revert_promotion` / `rescore`) are implemented and unit-tested; they have not been
exercised on field data.

## 4. Other results carried over (unchanged by this round)

**B. Deterministic explanation.** 18 platform scenarios, 10,008 repeated runs: 100% identical output, median 1.43 ms, p95 2.24 ms, no network
calls. Threat-signature matching on held-out settings (810 runs, rules frozen): Top-1 67.0%, Top-3 81.1%; low intensity 48.9% Top-1. Four
scenarios never match (`public_exposure`, `log_tampering`, `rogue_resources`; `organic_growth` is only ever ranked 2nd or 3rd). Scenario
definitions are shared with the rules, so this tests robustness to noise, intensity and cloud, not independently authored scenarios. Not
improved in this round; kept only as a dependent claim.

**C. Schema-free encoder** (synthetic data, one checkpoint). Level-shift AUC 1.00 on known and unseen schemas with online statistics;
spike AUC 0.68 on unseen schemas against 0.76 on known ones. Weak on spikes.

**D. Cohort cold start** (16 entities). Scoring starts in a median 12 h seeded against 156 h unseeded; +4σ shift detected 9/16 against 6/16;
false alerts per 100 scored 0.46 against 1.39. Small sample.

## 5. CoreStack control-plane evidence (`CORESTACK.md`)

Control-plane change events explain 0 of 78 real usage-metric shifts and about 16% of configuration-type shifts (95% interval for the
difference touches 0). Cohort co-movement has no discriminating signal on real data. Neither can gate promotion; both are kept only as
additive capped terms of the ledger allowance. The earlier control-plane pivot is not a lead claim.

## 6. Limitations (read these)

1. The dual trigger exceeds its 5% target on both development sets (10% and 8%; intervals 2–21% and 2–13%).
2. CoreStack thresholds did not transfer to fresh CoreStack; the fresh clean set has only 8 entities.
3. NAB entities are replicas of 14 (dev) and 22 (fresh) series with synthetic day order; 11–14 clusters is a small effective sample.
4. All attacks are team-generated additive shifts; no third-party attack data was available. Real shifts in CoreStack are real events of unknown cause.
5. The proposed design does not beat rollback on attack absorption over 60 days on NAB (0.17 against 1.00); it resolves far more legitimate change (85% against 44%). It sits at a different point on that trade-off.
6. The bound half of the dual trigger could not reach its half false-alert budget on either development set (false-alert floor about 8% on CoreStack); it was run at the loosest bound floor.
7. Tri-signal fusion, uncertainty-gated fallback and episode novelty do not exist in this repo and are not claimed.
8. Per-phase unit tests pass (211 across phase 0 and phase 2); the evaluation harness itself has no unit tests beyond smoke runs.

## 7. Iterations disclosed

Development used the same sets repeatedly; the fresh sets were run once after the freeze. Changes made during development, each on development data:
eligibility rule scale/std ≥ 0.05; dropping NAB-labelled anomaly days; per-bucket scale-proportional attack shifts; weekday/weekend
group-wise coherent drift (a single median across buckets let half the buckets absorb an attack, which weakened the earlier headline numbers);
a 0.5σ bound floor (flat real series produced zero bounds); the CUSUM comparator redesigned to daily means, then given outlier clipping;
a CUSUM governor reference rebuilt after a median/MAD-scale bug gave false trips; the ledger and its step unit; the dual trigger. Corrections to
earlier statements: the earlier "CUSUM fires on all 39 quiet CoreStack series" was a misreading (39 of 101 series alerted; the quiet set was
defined by the strategies themselves), the earlier claim that the per-window cap bounds absorption was false, and the earlier "bound = 10.35 ×
p99" is now stated as: bound = m × the entity's own 99th-percentile calibration drift, m a unitless multiplier tuned on separate series (9.92 on
NAB, 6.3 on CoreStack after the corrected statistic).

## 8. Reproduce

```
python -m evaluation.final_eval cs_dev tune ; python -m evaluation.final_eval nab_dev tune     # thresholds, development only
python -m evaluation.final_eval {cs_dev,nab_dev,cs_fresh,nab_fresh} eval                       # FPR_TARGET=0.10 for the secondary point
python -m evaluation.final_report <dataset> 0.05 ; python -m evaluation.absorb_compare <dataset> ; python evaluation/final_summary.py
```
Fresh NAB files come from `git clone --depth 1 https://github.com/numenta/NAB` (non-AWS categories copied to `data/external/nab_fresh/` as
`<category>__<file>.csv`). CoreStack series are derived pickles in `data/external/corestack/` (not committed).
