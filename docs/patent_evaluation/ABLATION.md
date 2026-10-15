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

### Confirmation

After the range is named on development data, the same variants and columns are run once on fresh2 (336 series, 158 resources). fresh2 has been
used for the earlier tuned and self-calibrated results, so it is not untouched for the full design; it has not been used for H, S, the
unlinked/unvalidated/no-cap variants, the interaction test or the sweep, and none of those were chosen after seeing it. Third-party data: see
`THIRD_PARTY.md` when written.
