# Component ablation, interaction test and allowance trade-off

Status: PLAN written and committed before the development results were read. Results are added below the plan.

Code: `evaluation/ablation_eval.py` (runs), `evaluation/ablation_report.py` (columns, tests), guard change in
`phase0/guard/drift_guard.py` (ledger provenance, `fixed_unit`, `promotion_mode="none"`), tests in
`tests/unit/phase0/test_drift_guard_ledger.py`.

## Plan

### Variants (all use the frozen self-calibrated bound; only the claimed parts change)

| Label | What is on | Notes |
|---|---|---|
| `adaptive` | nothing | production rolling baseline |
| `H` | claim 1 alone: validated bound + hold (freeze on first breach), no promotion path | a held entity stays held |
| `S` | claim 2 alone: shadow + stability-gated capped ledgered promotion, trigger = robust CUSUM (threshold tuned on dev), allowance a fixed 1 scale unit per step, no calibration validation | no displacement bound exists, so another trigger must start the shadow; this is the only part that needs one |
| `HS_unlinked` | both, but the allowance is a fixed 1 scale unit, not derived from the bound | tests the link |
| `HS_unvalidated` | both, bound used as computed (no alert exclusion, trend check or default fallback) | tests validation |
| `HS_nocap` | both, cap removed (stable shadow adopted in full, ledger still written) | tests the cap |
| `full` | both, allowance = allowance multiple x validated bound, ledger records the validation outcome | the design (freeze on hold) |
| `full_B` | the same with the original partial hold | as run on fresh2 |

### Outcomes and joint columns (fixed now)

Per entity, on clean (stable, ambient-free) entities: `fa` (false alert on the control run), `det3` (3 sigma stealth attack alerted within 50
days of the event), `abs3` (stored baseline carries at least 1.5 sigma of the attack at the end), `gflag`/`gunres` (injected
legitimate growth of at least 1 sigma alerted / still alerting or held at the end), `pdet` (poisoned calibration alerted), `goal`
(greedy attacker reaches 6 sigma stored displacement; only entities where it does against the adaptive baseline).

| Column | Definition | Population |
|---|---|---|
| C1 quiet and safe | not `fa` and `det3` and not `abs3` | clean entities |
| C2 and operable | C1 and not `gunres` | clean entities with growth >= 1 sigma |
| C3 governed under attack | not `fa` and `pdet` and not `goal` | clean entities where the greedy attacker succeeds against the adaptive baseline |

### Test that the design beats the sum of its parts

For each joint column Y: `I = Y(full) - Y(H) - Y(S) + Y(adaptive)` per entity, mean over entities, 95% interval from a bootstrap over whole resources.
`I > 0` with the interval above 0 is the claim "better than the two parts' separate gains added up". Also `Y(full) - max(Y(H), Y(S))`: whether
the design beats the better single part. A column counts as "none of them wins alone" only if no single part reaches the design's value.
If the interval includes 0 or is negative, that is the result and it is reported as such. The 2 x 2 is not a clean factorial:
claim 2 alone needs a different trigger (CUSUM), so the contrast is claim-level, not an isolated mechanism.

### Allowance sweep

Full design with the allowance varied: `allow_base` = 0.5, 1, 2, 4, 8, 16 validated bounds (linked) and `fixed_unit` = 0.25, 0.5, 1, 2, 4, 8 scale units
(unlinked), plus the ends (hold only; no cap). Two runs: with the change-event draws of the frozen protocol, and with change-event corroboration
forced off (`curve_ev0`: the stable shadow alone justifies the step; this is what the lead claim covers). Measured: share of 3 sigma stealth attacks absorbed
(stored baseline >= 1.5 sigma at end), stored displacement, detection, false alerts, share of flagged legitimate growth resolved at the end of the horizon,
share of real shifts resolved, greedy attacker reaching its goal. The run horizon is 40 days after the event (CoreStack 100-day series), so a slow allowance cannot finish a
large change within it; that is part of what the curve shows.

**Operating range rule, fixed before the results:** the range is every allowance setting on the evidence-off sweep with (a) at most 5% of 3 sigma
stealth attacks absorbed (point estimate) and (b) at least 50% of flagged legitimate growth resolved by the end of the horizon. If no setting
satisfies both, the report says so and gives the setting that comes closest to each. The range is named on development data only.

### Link contrast matched on step size (added before the sweep results were read)

`HS_unlinked` uses a fixed 1 scale unit, twice the 0.5σ floor that is the bound for most entities, so its difference from `full` mixes
the link with step size. The matched contrast is taken from the sweep: `L1` (allowance one validated bound) against `F0.5` (a fixed
allowance of 0.5 scale units), paired per entity, on C1 and C2 (no poisoned-calibration scenario is in the sweep, so not C3), on the
evidence-off sweep.

### Confirmation

After the range is named on development data, the same variants and columns are run once on fresh2 (336 series, 158 resources). fresh2 has been
used for the earlier tuned and self-calibrated results, so it is not untouched for the full design; it has not been used for H, S, the
unlinked/unvalidated/no-cap variants, the interaction test or the sweep, and none of those were chosen after seeing it. Third-party data: see
`THIRD_PARTY.md` when written.

## Development results (CoreStack dev: 101 series from 32 resources; 65 clean from 25 resources, 57 with growth of at least 1σ, 41 where the greedy attacker succeeds against the adaptive baseline, from 19 resources)

Design-stage data: variants and columns above were fixed before these were read, but this is the data the design was built on. Rates with 95%
intervals from a bootstrap over whole resources. Files: `ablation_ablation_cs_dev.json`, `ablation_results_cs_dev.json`.

| Variant | False alert | 3σ stealth detected | 3σ absorbed at end | Growth unresolved (of flagged) | Poisoned calibration detected | Greedy reaches goal | C1 | C2 | C3 |
|---|---|---|---|---|---|---|---|---|---|
| adaptive (no guard) | 0% (0-0) | 58% (50-67) | 100% (100-100) | 2% (0-8) | 2% (0-5) | 100% (100-100) | 0% | 0% | 0% |
| H: claim 1 alone (validated bound + hold) | 3% (0-7) | 98% (94-100) | 11% (4-19) | 100% (100-100) | 100% (100-100) | 0% (0-0) | 86% (79-93) | 25% (14-36) | 95% (88-100) |
| S: claim 2 alone (CUSUM trigger, shadow, capped ledger, fixed 1σ) | 0% (0-0) | 68% (57-78) | 54% (44-64) | 66% (48-83) | 66% (56-75) | 22% (11-35) | 46% (36-57) | 18% (9-27) | 51% (34-66) |
| both, allowance fixed at 1σ (not from the bound) | 3% (0-7) | 98% (95-100) | 37% (28-46) | 52% (35-69) | 100% (100-100) | 10% (2-18) | 60% (50-70) | 33% (23-44) | 85% (77-94) |
| both, bound not validated | 3% (0-7) | 97% (92-100) | 22% (13-30) | 51% (35-68) | 100% (100-100) | 12% (5-20) | 75% (66-85) | 44% (30-58) | 83% (75-92) |
| both, no cap (stable shadow adopted in full) | 3% (0-7) | 98% (94-100) | 78% (69-88) | 18% (7-30) | 100% (100-100) | 85% (73-97) | 18% (8-29) | 11% (4-17) | 15% (3-28) |
| **full** (claim 3: both, allowance from the validated bound, ledger records validation) | 3% (0-7) | 98% (94-100) | 20% (12-27) | 50% (32-67) | 100% (100-100) | 12% (5-21) | 77% (68-85) | 46% (31-60) | 83% (74-92) |
| full with partial hold (as run on fresh2, `B`) | 3% (0-7) | 98% (94-100) | 28% (18-38) | 48% (29-64) | 100% (100-100) | 56% (38-75) | 69% (59-79) | 42% (26-58) | 41% (23-62) |

### Does the design beat the sum of its parts? Not on the pre-declared test.

| Column | adaptive | H | S | full | Interaction `full - H - S + adaptive` (points) | `full - max(H, S)` (points) |
|---|---|---|---|---|---|---|
| C1 quiet and safe (n = 65) | 0% | 86% | 46% | 77% | **-55** [-68, -44] | -11 [-19, -4] |
| C2 and operable (n = 57) | 0% | 25% | 18% | 46% | **+4** [-13, +21] | **+18** [+4, +32] |
| C3 governed under attack (n = 41) | 0% | 95% | 51% | 83% | **-63** [-84, -41] | -12 [-21, -4] |

* The pre-declared super-additivity test **is not met on any column**: the interaction is strongly negative on C1 and C3 and indistinguishable
  from 0 on C2. Claim 1 alone already earns most of C1 and C3, so there is little left for a combination to add (a ceiling effect that this
  additive test cannot see past).
* **C2 is the column that none of the parts wins alone** (H 25%, S 18%) and the design reaches 46%, 18 points above the better part (interval
  above 0). That is "better than either part", not "better than the sum of the two parts' gains" (interaction +4, interval includes 0).
* On C1 and C3 hold-only is better than the design by 11 and 12 points: promotion costs about 9 points of absorption (20% against 11%).
* The S variant uses a different trigger (CUSUM), so the 2 x 2 is a claim-level contrast, not an isolated factor.

### What each ingredient adds (full minus the variant, points of each column)

| Ingredient removed | C1 | C2 | C3 | Reading |
|---|---|---|---|---|
| Cap (stable shadow adopted in full) | +58 [46, 71] | +35 [20, 51] | +68 [58, 79] | **the cap is what makes promotion safe**: without it 78% of 3σ attacks and 85% of greedy attackers succeed |
| Freeze on hold (partial hold instead) | +8 [-3, 18] | +4 [-6, 13] | +41 [26, 58] | matters for the greedy attacker |
| Allowance fixed at 1σ instead of derived from the bound | +17 [7, 27] | +12 [4, 22] | -2 [-8, 0] | **confounded with step size**: 1σ is twice the 0.5σ floor that is the bound for most entities; see the matched contrast below |
| Bound not validated | +2 [0, 5] | +2 [0, 6] | 0 [0, 0] | **validation adds almost nothing to the self-calibrated bound on this data** (the bound is the floor for 62% of entities and the resampled bound is already robust to a poisoned ramp); the earlier tuned-design ablation (39/39 against 28/39) is where validation mattered |

**The link, matched on step size** (sweep below, evidence off): allowance of one validated bound (`L1`) against a fixed 0.5σ (`F0.5`), paired per
entity: C1 -1.5 points [-4.8, 0.0]; C2 0.0 [0.0, 0.0]; 3σ attack absorbed +1.5 [0.0, 4.8]; growth unresolved -1.8 [-5.5, 0.0]. **Deriving
the allowance from the validated bound is not shown to be better than a fixed allowance of the same median size**; it differs only for the 38% of
entities whose bound is above the floor. What the link adds is that one validated number governs both trigger and release, and that the
ledger can record it (unit-tested); not a measured gain.

## Allowance trade-off (CoreStack dev, stable shadow alone justifies the step)

Figure: `allowance_curve_ev0_cs_dev.png` (`allowance_curve_curve_ev0_cs_dev.json`; with the frozen protocol's change-event draws the shape is the
same, `allowance_curve_curve_cs_dev.json`). Allowance in multiples of the validated bound; for the median entity one bound is 0.5σ. n as above (clean 65,
growth 57, shifted 29).

| Allowance per step | σ at median entity | 3σ attack absorbed | Stored displacement, median / p90 (σ) | Fast 4σ attack absorbed | Flagged growth resolved | Real shifts resolved | Greedy reaches goal | 3σ detected | False alert |
|---|---|---|---|---|---|---|---|---|---|
| hold only (0) | 0 | 11% (4-18) | 0.45 / 1.46 | 11% (4-19) | 0% (0-0) | 0% (0-0) | 0% (0-0) | 98% (94-100) | 3% (0-7) |
| 0.5 bounds | 0.25 | 11% (4-18) | 0.63 / 1.73 | 42% (29-54) | 48% (31-64) | 25% (5-50) | 8% (3-13) | 98% (95-100) | 3% (0-7) |
| **1 bound (default)** | 0.5 | 12% (5-20) | 0.87 / 1.87 | 52% (40-63) | 50% (32-67) | 35% (14-58) | 8% (3-13) | 98% (95-100) | 3% (0-7) |
| 2 bounds | 1 | 35% (25-45) | 1.37 / 2.16 | 94% (84-100) | 50% (33-67) | 50% (24-78) | 11% (4-18) | 98% (95-100) | 3% (0-7) |
| 4 bounds | 2 | 78% (69-88) | 2.37 / 3.25 | 94% (84-100) | 60% (47-72) | 55% (30-79) | 11% (4-18) | 98% (94-100) | 3% (0-7) |
| 8 bounds | 4 | 78% (69-88) | 3.00 / 3.53 | 94% (84-100) | 82% (70-93) | 60% (35-84) | 23% (12-35) | 98% (95-100) | 3% (0-7) |
| 16 bounds | 8 | 78% (69-88) | 3.00 / 3.53 | 94% (84-100) | 82% (69-93) | 60% (33-85) | 55% (46-63) | 98% (94-100) | 3% (0-7) |
| no cap (adopt in full) | ∞ | 78% (69-87) | 3.00 / 3.53 | 94% (84-100) | 82% (70-93) | 65% (40-89) | 55% (45-64) | 98% (94-100) | 3% (0-7) |

* **The pre-declared range rule is not met by any setting.** Condition (a), at most 5% of 3σ attacks absorbed, fails everywhere because hold alone
  already leaves 11% absorbed: those are entities whose own bound is 1.5σ or more, so the bound itself lets 1.5σ in. Nearest to (a): 0.5 to 1
  bounds (11-12%); nearest to (b), at least 50% of flagged growth resolved: 1 bound already reaches 50.0% (32-67), 8 bounds 82%.
* **Post hoc, descriptive (not the pre-declared rule):** the curve has a cliff. Absorption stays at the hold-only level for 0.5 to 1 bounds
  (11-12%), triples at 2 bounds (35%), and from 4 bounds on equals adopting the shadow in full (78%), while about half of flagged growth is
  already resolved at 0.5 to 1 bounds. **Proposed operating range: 0.5 to 1 validated bounds per step, default 1** (about 0.25 to 0.5σ at
  the median entity). The cap is then a tunable parameter with a measured shape rather than a fixed number; the range is an
  observation on development data, to be confirmed on fresh2.
* **Cost inside that range.** A fast 4σ attack is absorbed (1.5σ or more stored at the end) for 42% to 52% of entities, against 11% for hold alone:
  the allowance does not protect against fast large attacks beyond what the hold does. Real shifts resolved are 25% to 35%.
* **Horizon caveat.** CoreStack dev series run 40 days after the event. A shadow needs 14 stable days plus 14 prior days, so the first promotion is
  due about 28 days after the hold and at most one step fits in the horizon. This curve is therefore a single-step-size curve; the
  rate limit (steps at least 14 days apart) is covered by `GUARANTEE.md` and, over a longer horizon, by the NAB sweep (pending, synthetic
  ordering).
* The unlinked (fixed σ) and linked (bound multiples) curves coincide because the median bound is 0.5σ.

## Planned confirmation on fresh2: predictions written before the fresh2 results were read

fresh2 (336 series, 158 resources; horizon 30 days after the event, bound is the floor for 98% of series). Predictions: hold-only will be at or above the design on C1
and C3 (interaction not above 0); the cap contrast will again be large; the validation contrast and the matched link contrast will be about 0
(98% of bounds are the floor, so linked and fixed 0.5σ allowances are identical for them); growth will be unresolved at almost every setting because at most one step fits in 30 days
(earlier fresh2 result 99% unresolved); the proposed range will not be distinguishable from hold-only on absorption. Any column or contrast that
disagrees with this is reported as it comes out.

---

# Earlier component ablation (tuned design, from the frozen-design runs, no new runs)

Kept from the earlier version of this file. It describes the tuned design (`FINAL_TABLES.md`), not the self-calibrated design tested above; its
"Not run" list is what the plan above now covers.

Cells: dev / fresh where both exist. Source: `FINAL_TABLES.md`. Intervals are in that file. NAB = day-resampled replicas, synthetic
order, dependent entities; CoreStack = real Azure telemetry. All attacks are team-generated.

| Variant | Parts present | False alerts | 2σ stealth detected | Poisoned calibration caught | Growth unresolved |
|---|---|---|---|---|---|
| Clipped CUSUM | trigger only, no hold of a validated bound, no ledger | NAB 3% / CS 0% | 92% / 65% | 95% / 66% | 84% / 69% |
| Validated bound + hold | bound, hold, shadow; promotion only by the old cohort-agreement rule, which did not resolve growth (100% unresolved) | 10% / 8% | 8% / 14% | 99% / 98% | 100% / 100% |
| Validated bound + hold + ledger | adds capped promotion and ledger | 10% / 8% | 8% / 14% | 99% / 98% | 41% / 25% |
| CUSUM trigger + validated reference + ledger | sequential trigger, hold, shadow, ledger | 4% / 0% | 92% / 68% | 97% / 68% | 9% / 64% |
| Dual trigger, no ledger | both triggers, hold, shadow; same old promotion rule | 10% / 8% | 94% / 68% | 100% / 98% | 100% / 100% |
| **Dual trigger + ledger (proposed)** | all | 10% / 8% | 94% / 68% | 100% / 98% | 6% / 25% |

(NAB dev / CoreStack dev in each cell.)

## What each part buys, as measured

* **Validated bound and hold** supply poisoned-calibration catching (66% to 98% on CoreStack dev against the trigger alone) and
  nothing for stealth ramps on their own (8% on NAB dev).
* **The sequential trigger** supplies stealth detection (8% to 94% on NAB dev; 14% to 68% on CoreStack dev).
* **The ledger** supplies resolution of growth (100% unresolved to 6% on NAB dev; 100% to 25% on CoreStack dev) and does not
  change detection or false alerts.
* **No single part does all three.** The trigger alone misses poisoned calibration on real data and never resolves growth; the
  bound alone misses stealth ramps; neither resolves growth without the ledger. This is the argument that the combination is
  more than a list of parts, but it rests on dev data and the interaction itself (as opposed to additive effects) has not been
  tested.

## Not run

Hold without a shadow, a shadow without a hold, an unvalidated bound on the frozen design (an earlier ablation gave 21/21 vs 1/21
on NAB and 39/39 vs 28/39 on CoreStack), and any variant on fresh data beyond what `FINAL_TABLES.md` already contains.
