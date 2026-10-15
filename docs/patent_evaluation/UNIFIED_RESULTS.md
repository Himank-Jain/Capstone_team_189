# Results for the unified scope (guard + explanation + schema-free), 15 October 2026

The team adopted the structure of "Unified, poison-resistant behavioral anomaly detection with deterministic root-cause guidance for
multi-cloud environments" (25 slides) as the project scope. That file's figures (93.6% detected, 94.0% top-3, 91.4% promoted, 2,140
entities, 40 events against 410) are **planned figures, not results of this repository**; none of them was copied. This note records what
was measured on the repository's own data after the scope change. Not legal advice. Every attack is team-generated (or a strategy from a
paper that we implemented); CoreStack telemetry is real, NAB and the long-horizon orders are synthetic.

Data: `cs_dev` (101 series, 32 resources, 100-day compressed timeline), `cs_fresh2` (336 series, 158 resources, 90-day timeline; same customer
dump as dev), `cs_long` (dev series with days after day 60 re-drawn in day-type order, 200 days), `nab_dev` (synthetic order, dependent entities).

## A. The guard (existing evidence, restated for the unified deck)

Design as frozen in `SELFCAL.md` (self-calibrated bound, floor 0.5σ, hold at the first breach, shadow, capped ledgered promotion).
Fresh2, 311 clean series from 148 resources, 30 days after the event; intervals are 95% bootstrap over resources
(`final_results_cs_fresh2_0.05B.json`).

| Strategy | False alerts | 3σ detected | Fast 4σ detected | Poisoned calibration caught | 3σ absorbed at end | Flagged growth unresolved |
|---|---|---|---|---|---|---|
| Adaptive baseline (reference) | 0% (0-0) | 81% (76-86) | 84% (79-88) | 2% (1-4) | 15% (9-22) | 2% (0-4) |
| Frozen | 1% (0-2) | 12% (6-18) | 15% (9-22) | 14% (8-20) | 0% | 81% (58-100) |
| Longer window | 0% (0-0) | 80% (75-85) | 82% (76-86) | 3% (1-5) | 0% (0-1) | 2% (0-5) |
| Update clipping | 10% (5-16) | 84% (79-88) | 85% (80-89) | 15% (9-21) | 15% (9-22) | 24% (16-31) |
| Rollback | 0% (0-0) | 81% (76-86) | 84% (79-88) | 74% (67-80) | 4% (2-8) | 71% (65-77) |
| Clipped CUSUM | 9% (4-14) | 79% (74-84) | 80% (75-85) | 79% (74-84) | 15% (8-22) | 79% (74-84) |
| Dual trigger (tuned) | 9% (4-14) | 79% (74-84) | 80% (75-85) | 85% (80-89) | 5% (2-8) | 13% (6-20) |
| **Design (self-calibrated, ledger)** | **0% (0-1)** | **85% (80-89)** | **85% (80-89)** | **85% (80-89)** | **0% (0-1)** | **99% (97-100)** |

Reading, stated in the same breath:

* What the design adds on fresh data is **stored-state integrity under a poisoned calibration** (85% against 2% for the adaptive baseline) and a 0%
  absorbed 3σ attack at 0% false alerts. Plain detection of the injected attack is the same as the unguarded baseline (85% against 81%).
* The cost is operability: 99% of flagged legitimate growth is still unresolved after 30 days (adaptive 2%; rollback 71%; tuned dual trigger 13%).
* Rollback has a poisoned-calibration catch rate of 74% (67-80), a strong rival that was missing from the earlier fresh table.
* **Horizon.** The 0% absorbed figure holds for a 30-day horizon, in which no promotion step can complete. Over 100 days a 3σ attack is absorbed in 98-100% of
  series and a greedy attacker reaches its goal in 65% (CoreStack, day-resampled) and 99% (NAB) of series (`ABLATION.md`). The effect of the guard is **delay**
  and an audit trail, not exclusion.
* 98% of fresh2 bounds are the fixed 0.5σ floor, so the false-alert rate comes from that constant, not from the resampling (62% on dev).

### A2. Growth and migration: how fast is a flagged legitimate shift resolved

The target deck claims 91.4% of 140 injected growth events promoted correctly with a median of 9 days. Our default allowance (one validated bound per step,
steps at least 14 days apart, stability-gated) on the long sets (`ablation_curve_ev0_*`, `ablation_report`):

| Set (default allowance, one validated bound per step) | Flagged growth resolved at +30 d / +60 d / +100 d | 3σ attack absorbed at +30 d / +60 d / +100 d | Hold only: growth resolved; 3σ absorbed at +100 d |
|---|---|---|---|
| `cs_long` (day-resampled CoreStack, 75 clean series / 28 resources) | 26% / 70% / 57% | 7% / 100% / 100% | 0%; 8% |
| `nab_dev` (synthetic order, dependent entities, 118 clean / 14 resources) | 18% / 67% / 74% | 14% / 63% / 98% | 0%; 48% |

Growth that is a persistent level shift and an attack at the same level are the same input to a stability-gated promotion; the allowance sets the speed, not the
outcome (`ABLATION.md` section on long horizons). The cohort-agreement rule of the target deck (>= 60% of cohort neighbours shifted, shadow stable under 0.25σ over 14
days) is the rule already in `phase0/guard/drift_guard.py` (`cohort_agreement = 0.60`, `shadow_stability_sigma = 0.25`). It resolved **0% of growth** with the old
rule alone (100% unresolved, `ABLATION.md`), and on real CoreStack shifts cohort co-movement is as common in random windows as in natural shifts (lift 0.9x,
`CORESTACK.md`). It is kept as a dependent fallback with no measured value. The 91.4% is not reproduced.

## B. Deterministic explanation

### B1. Does attribution name the metric that was moved (real telemetry; protocol `PREREG_UNIFIED_B.md`)

Each metric of a resource is the target once; a scenario is added to the target only; the other metrics of the resource are the real series (their natural
variation is the distractor). The existing `MetricAttributor` (threshold 3.0) ranks the metrics by their 24 hourly readings of the probe day, standardised against
the **trusted snapshot** (days 0-29, never updated) or the **adaptive rolling window**. Variant `pk24` (peak = the daily coherent median) was chosen **after** the
dev result of the module default; both variants are stored. Top-1 rank of the target, 95% intervals by bootstrap over resources.

| Set (probe) | Scenario | Snapshot top-1 | Adaptive top-1 | Snapshot minus adaptive |
|---|---|---|---|---|
| dev, 18 resources (day 85, end of ramp) | stealth 3σ | 65% (49-82) | 76% (61-89) | -11 (-30, +9) |
| dev (day 99, 39 days after the event) | stealth 3σ | 65% (49-80) | 22% (10-37) | **+43 (+17, +66)** |
| dev (day 99) | fast 4σ | 67% (53-82) | 11% (5-19) | **+57 (+36, +75)** |
| fresh2 non-network, 34 resources (day 85) | stealth 3σ | 67% (55-78) | 67% (56-77) | 0 (-4, +5) |
| fresh2 non-network (day 89, 30 days after the event) | stealth 3σ | 83% (74-92) | 84% (75-92) | -1 (-6, +3) |
| `cs_long`, 18 resources (day 85) | stealth 3σ | 77% (60-94) | 67% (45-87) | +10 (-12, +30) |
| `cs_long` (day 199, 139 days after the event) | stealth 3σ | 65% (47-84) | 22% (20-24) | **+43 (+27, +62)** |
| `cs_long` (day 199) | fast 4σ | 75% (57-92) | 22% (20-24) | **+53 (+37, +68)** |

* Top-1 at the snapshot is 42-71% on dev and 47-83% on `cs_long`. On fresh2 non-network resources it is 65-94%; the 94% is a fast 4σ attack 10 days after the event, where the adaptive reference
  is also 98%. The target deck's 94.0% is top-3 on a different test. Top-2 at the snapshot is 67-100%, and top-3, where a resource has at least five metrics, 85-100%.
* The snapshot reference beats the adaptive one only **after the adaptive baseline has absorbed the shift** (39 days after the event on dev, 139 on `cs_long`); on fresh2, 29 days after the event, it is as good, and early in the event it is worse (dev day 70, 10 days after the event: -33 points).
* Control runs (no scenario): 0.4 to 0.8 non-target metrics flagged per case at the snapshot on dev, 0.1 to 0.8 on fresh2 non-network. The explanation has to say so.
* `cs_fresh2` over all 85 resources reads 86-98% top-1 because 51 resources are Public IP series whose other metrics are flat zero; that is not a result.

### B2. Cause category and reproducibility

* **Cause category.** Real telemetry carries no cause labels, so this cannot be measured on it. The labelled test is the synthetic demo generator with a constant
  baseline: 810 held-out runs (18 scenarios, 5 seeds, 3 intensities, 3 clouds), threat-signature **top-1 67.0%, top-3 81.1%**. Scenario definitions are shared with the rules,
  so this tests robustness to noise, not independence. The 88.1% of the target deck is not reproduced. Three scenarios (public exposure, log tampering, rogue resources) match 0 of 45.
* **Reproducibility** (`scripts/determinism_check.py`, `determinism_check.json`): 54 cases (18 scenarios x 3 clouds), the explanation chain (`ExplanationBuilder.build`: rules, confidence,
  threat signatures, knowledge base) run 250 times each = **13,500 runs, one distinct output per case (54 of 54)**, no network connection attempted. This is process-level determinism:
  same interpreter, same rule and knowledge-base files. Median **0.17 ms** (p95 0.34 ms) for the build alone; it excludes evidence building and the API. The target deck's "41 ms median, zero external calls" is a
  different scope and is not compared.

## C. Schema-free representation

Registry checkpoint 0.1.0 (126 metric names, 20 entity types), 32-event windows, AUC of the cosine distance to the baseline centroid between negative windows
(days 30 to the event) and windows after an injected 3σ shift (10-day ramp). In-vocabulary entities may have been seen in training (the checkpoint was trained on the team corpus),
so the contrast with renamed inputs and the genuinely unseen schemas is the evidence. Comparator without learning: |median(window) - median(baseline)| / robust scale.

| Condition | dev (100 entities, 31 resources) | fresh2 (156 entities, 91 resources) |
|---|---|---|
| Encoder, names as recorded | 0.59 (0.57-0.61) | 0.56 (0.54-0.59) |
| Encoder, names unseen, raw value passes through | 0.62 (0.58-0.67) | 0.61 (0.57-0.66) |
| Encoder, names unseen, per-metric statistics learned online | 0.66 (0.62-0.70) | 0.62 (0.60-0.65) |
| Per-metric z-score, no learning | **0.98 (0.96-1.00)** | **0.83 (0.78-0.87)** |
| Encoder on the genuinely unseen schema (fresh2, 180 entities / 68 resources) | 0.50 | 0.50 (z-score: 1.00) |

At a 10σ shift on dev the encoder reaches 0.68 in vocabulary and 0.68 renamed-online, against 1.00 for the z-score. The earlier synthetic test (30 entities) had level-shift AUC 1.00
in vocabulary and 1.00 with online statistics against 0.34 with passthrough; that test does not carry over to real series. **Invention C is not supported on real data**: the encoder does not
detect these shifts, with or without the schema. Retraining the encoder on these series (the comparator "a model retrained for those types") was not done. The only supported form of the claim
is the per-metric statistic, which is not new.

## D. Cohort cold start (`evaluation/cold_start_cs_eval.py`, `cold_start_report.py`)

A new entity streams hourly readings from hour 0; the seeded variant borrows the shape of other resources of the same (entity type, metric) after 24 readings (leave-resource-out, groups with
at least three resources); a persistent +4 scale-unit shift at hour 48. Paired difference, 95% bootstrap over resources.

| Set | Scoring starts (median) | Detected within the window: unseeded | seeded | Difference | False alerts per 100 scored readings (mean): unseeded | seeded |
|---|---|---|---|---|---|---|
| dev, 87 entities / 25 resources | 156 h | 40% (30-50) | 61% (56-66) | **+21 points (+9, +33)** | 6.3 (4.4-8.8) | 2.5 (1.0-4.4); paired -3.8 (-5.2, -2.2) |
| fresh2, 314 entities / 151 resources | 156 h | 5% (2-9) | 34% (28-41) | **+29 points (+23, +35)** | 1.8 (1.0-2.7) | 1.8 (0.9-2.9); paired +0.0 (-0.5, +0.5) |

Scoring starts 144 hours earlier at the median in both sets. The effect replicates on a larger set and is the one supported part of the target deck's cold-start claim; the "40 events against 410"
figure is not reproduced (our units are hours and a different protocol). Cross-cloud seeding is not tested: within a group all resources share one cloud. The effect of seeding on a guard calibration
check (the target deck's cohort cross-check) is the tuned-design result in `FINAL_TABLES.md`; with the self-calibrated bound that check raised false alerts (D2b).

## E. Incident collapsing during a hold (`evaluation/collapse_eval.py`, `collapse_report.py`)

Frozen design, hold and promotion as above. Per run: days an uncollapsed alerting would flag after the event, incidents opened, and the share of those days that attach to an already open incident.

| Scenario | Runs with flags (dev / fresh2) | Median flag-days | Median incidents | Share of flag-days that attach to an open incident |
|---|---|---|---|---|
| stealth 3σ | 75 of 101 / 276 of 336 | 11 / 15 | 1 / 1 | 33% / 6% |
| fast 4σ | 92 / 286 | 7 / 10 | 1 / 1 | 38% / 10% |
| benign growth | 71 / 268 | 6 / 8 | 1 / 1 | 29% / 8% |

The operator sees about one incident per affected entity, against roughly 6 to 15 flag-days. Most flag-days do not attach to an open incident (they occur before it opens); the target deck's "1 incident against 212 alerts"
is not reproduced and the unit differs (days, not alerts). A small effect.

## F. Not done, and why

* **B2 cause category on real telemetry**: no labels exist; the synthetic result stands.
* **A retrained encoder as the comparator for C**: heavy; the negative result does not depend on it (the z-score already wins by a wide margin).
* **Windowed plus cumulative bound with 1.25 x p99 of D on benign history** (target deck): not adopted. The evidenced design derives the bound from the maximum displacement over 80 day-type-resampled clean
  futures (98.75th percentile) and keeps the fixed floor; the promotion step plays the role of the windowed bound. Changing it now would void the frozen design.
* **Tri-signal fusion and uncertainty-gated fallback**: not built; they stay out of the claims (`CLAIMS.md` section 5). The contrastive encoder exists (`phase1/models/tstcc_encoder.py`) but did not detect shifts on real series (C).
* **Live validation in CoreStack's environment on attacks the team did not generate**: not done. No public poisoning data is reachable.
* **Size**: 336 series, same customer dump as dev; the target deck's 2,140 entities over 9 months are not available.
