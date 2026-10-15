# Patent evaluation: measured results

All numbers below come from the scripts in this repo and the JSON beside this file.
Nothing here is a target or an estimate. Not legal advice; no formal prior-art search has been done.

## What the data is, and is not
* **Real telemetry:** the 17 AWS CloudWatch series of the public Numenta Anomaly Benchmark (EC2 CPU, EC2 network/disk, ELB, RDS CPU).
* **No CoreStack data and no Azure/GCP data** were used. Nothing here supports a claim about CoreStack production data.
* Each source is only ~14 days long, so 203 220-day "entities" were built by resampling real days (weekday/weekend matched, smoothed, with NAB-labelled anomaly days removed). Level, noise and daily shape are real; the order of days is synthetic.
* Attacks (slow ramps of 30/60/90 days to 4/6/8 scale units), benign growth, poisoned calibration, cohort-wide poisoning and an adaptive attacker are **simulated** on that data.
* Harness choices were made on control and benign data only (smoothing, daily-mean CUSUM, scale eligibility, margin). They are listed under "Iterations".

## A. Drift guard (203 entities; 41 quiet entities for attack comparisons, 96 held out for control rates)
| Strategy | Stored drift at ramp end (median σ) | Slow ramps alerted | Alerts on clean control | Real growth flagged |
|---|---|---|---|---|
| Adaptive baseline (Phase 0) | 2.62 | 25 / 41 | 35 / 96 | 16 / 41 |
| Frozen baseline | 0.00 | 41 / 41 | 18 / 96 | 27 / 41 |
| Long window (90) | 0.67 | 36 / 41 | 6 / 96 | 18 / 41 |
| Update clipping (k=3) | 2.55 | 38 / 41 | 53 / 96 | 21 / 41 |
| CUSUM (daily mean) | 2.62 | 41 / 41 | 35 / 96 | 35 / 41 |
| Rollback | 0.46 | 25 / 41 | 41 / 96 | 16 / 41 |
| **Drift guard, calibrated** | **1.02** | **41 / 41** | **36 / 96** | **28 / 41** |

Honest reading:
* The guard bounds stored drift (1.02σ vs 2.62σ) and alerts on every ramp, including 90-day ramps where the adaptive baseline alerts on 5 / 14.
* It is **not better than the simple alternatives** on these measures: a long window has less drift and far fewer control alerts; a frozen baseline has zero drift. The guard is also **slower to first alert** (median 26 vs 20 days).
* "Slow ramps alerted" saturates for several strategies, so this comparison does not separate them well. Attack strength was large (4 to 8 scale units).
* Control alert rate of the guard (36 / 96) is as high as the adaptive baseline's: the z-detector alerts on many resampled-real entities regardless of the guard.

Where the guard differs:
* **Poisoned calibration** (attacker present while bounds are learned): validation rejected the poisoned calibration in 96 / 96 runs; attacks were then still alerted 41 / 41, stored drift 1.93σ. Without validation: 2 / 41 alerted, 4.17σ.
* **Adaptive attacker** who ramps to the bound (median 0.98σ) then jumps: a 2σ payload evaded in 7 / 41 (guard) vs 30 / 41 (adaptive baseline); 3σ: 1 / 41 vs 9 / 41; 4σ and above: none evaded either.
* **Real growth:** the frozen baseline flags real growth forever. The guard raises one incident and promotes: 25 / 26 cohort-wide shifts promoted (median 19 days); 31 / 32 isolated shifts promoted after operator approval, 0 / 32 without it.
* **Limit:** an attack that shifts the whole cohort passes the cohort test and was promoted in 96 / 96 runs (median 26.5 days). Operator review is the only backstop.
* Calibrated bounds: median 0.78σ windowed, 0.86σ cumulative; margin 10.35 (tuned on 107 held-out entities).

## B. Deterministic explanation
* 18 platform scenarios, 10,008 repeated runs: 100 % identical output, median 1.43 ms, p95 2.24 ms, 0 network connection attempts.
* Threat-signature matching: Top-1 14 / 18, Top-3 15 / 18. These scenarios come from the same generator the rules were written against, so this is **in-sample**, not an independent accuracy estimate.

## C. Schema-free encoder (30 synthetic entities per condition; repo checkpoint `synthetic_32`)
| Condition | Level shift AUC | Spike AUC |
|---|---|---|
| Known schema | 1.00 | 0.76 |
| Unseen schema, old pass-through | 0.34 | 0.50 |
| Unseen schema, online statistics (new) | 1.00 | 0.68 |

Spikes remain weak on unseen schemas. Data is synthetic; this tests robustness to schema change on this checkpoint only. No retraining was done.

## D. Cohort cold start (16 entities, leave-source-out cohort)
| | Scoring starts (median h) | +4σ shift detected | Median delay (h) | False alerts per 100 scored |
|---|---|---|---|---|
| Unseeded | 156 | 6 / 16 | 144.5 | 1.39 |
| Seeded | 12 | 9 / 16 | 50 | 0.46 |

Seed spread was chosen on clean-data false alerts only (a narrower spread gave 10.6 false alerts per 100). Small sample.

## Not implemented
Tri-signal fusion, uncertainty-gated fallback and episode novelty (listed as dependent features in the deck) do not exist in this repo and are not evaluated.

## Iterations disclosed
Harness changes during development, each decided on control or benign data: eligibility rule scale/std >= 0.05; dropping NAB-labelled anomaly days; per-bucket scale-proportional attack shifts; entity-level (median across buckets) drift; smoothed bootstrap and a 60-day calibration period; clip k=3 (k=1 was a strawman); CUSUM redesigned to daily means after hourly versions alarmed constantly; margin tuned on held-out entities. Attack results from earlier pilots were seen, so the harness is not fully blind.
