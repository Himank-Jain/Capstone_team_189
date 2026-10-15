# Pre-registration: Invention B (metric attribution) on real telemetry, written before the run

Written 15 October 2026 after the target deck ("Unified, poison-resistant behavioral anomaly detection with deterministic
root-cause guidance") was adopted as the project scope. Its explanation figures (94.0% of injected cause metrics in the top three,
88.1% correct cause category) are not results of this repository; the existing explanation numbers (`explanation_heldout.json`,
67.0% top-1 and 81.1% top-3 over 810 runs) come from the synthetic demo generator with a constant baseline, not from real telemetry.
This note fixes the test on real CoreStack telemetry before it is run.

## Question B1

When one metric of a resource is moved by an injected scenario and the other metrics of the resource stay as recorded, does the
existing `MetricAttributor` rank the moved metric first, and does the answer depend on the baseline the readings are
standardised against: the trusted snapshot of claim 1 (days 0-29, never updated) or the adaptive rolling window (the 30 most recent
same-bucket readings, which follows whatever the target metric has been doing)?

## Design (fixed)

* Data: `cs_dev` (CoreStack, 100-day compressed timeline) and `cs_fresh2` (336 series from 158 resources, 90-day timeline). Resources
  with at least 3 eligible metrics (`evaluation.runner.eligible`). Each metric of a resource is the target once.
* Scenarios on the target only: stealth 2σ and 3σ (ramp = `LONG_RAMP`), fast 4σ (10-day ramp), and a no-scenario control.
  Magnitudes in the target's own bucket scale, as everywhere in the harness.
* Probe days: event + 10, event + ramp + 5, last day. Observation = the 24 hourly readings of that day; every reading is
  standardised against its (hour, day type) bucket of the reference; the standardised readings go to `MetricAttributor` with a
  constant (0, 1) lookup, threshold 3.0 and the 3-reading peak, i.e. the module unchanged.
* Outcomes: rank of the target (1 = best); top-1; top-2; flagged (contribution at least 3.0); number of other metrics flagged
  (false attributions, a count of distractors, not an error rate against ground truth because real series do shift).
* Analysis: paired by (resource, target, scenario, probe); 95% intervals by bootstrap over resources. Top-3 is reported only where a
  resource has at least 5 metrics, because with 3 or 4 metrics it cannot fail.

## Predictions, written before the run

1. At the end-of-ramp probe, the snapshot ranks the target first in at least 85% of stealth 3σ and fast 4σ cases.
2. The adaptive reference ranks the target first less often than the snapshot at the last probe (the baseline has followed the
   shift) by at least 10 points for stealth 2σ and 3σ; at the first probe the difference is smaller.
3. The snapshot flags more non-target metrics than the adaptive reference in the control runs (the snapshot does not follow natural
   change); this is the cost of the reference and is reported, not hidden.
4. The measured top-1 is below the 94.0% of the target deck on at least one of the two datasets.

## What would change the claim

* If the snapshot is not better than the adaptive reference at the last probe, the link "attribution runs against the trusted
  snapshot" (claim 3 of the target deck) has no measured value and stays a dependent feature.
* If the snapshot flags more than one non-target metric per control run on average, the explanation must say so (UNKNOWN or
  LOW confidence), and the claim is stated with that cost.

Nothing in the module (threshold 3.0, peak window 3, floors) is tuned on either dataset.

---

## Amendment and results (15 October 2026, after the runs)

**Disclosure about the design.** The first run used the module unchanged (peak of 3-reading medians, variant `pk3`). Prediction 1 failed on
`cs_dev` (snapshot top-1 33 to 61%). I then added an option to `MetricAttributor` (`peak_window`, default unchanged at 3) and a variant `pk24`
(the daily coherent median: all 24 readings of the day) **after seeing the dev result for `pk3`**. `pk24` is therefore dev-informed; both variants
are stored in `attribution_<dataset>.json` and the summaries (`attribution_summary_*_pk3.json`, `*_pk24*.json`). Numbers below are `pk24`.
`cs_fresh2` and `cs_long` were run for both variants after the choice, so they are not independent of it on the design, only on the data.

**Subsets.** `cs_fresh2` has 85 resources with exactly 3 metrics each; 51 of them are `Microsoft.Network` resources (Public IP) whose other metrics are
flat zero, so the target is trivially first. The meaningful number is the 34 non-network resources (`_nonet`). `cs_dev` and `cs_long` have 18 resources
(3 to 7 metrics) and no network resources.

**Predictions against results (snapshot reference, `pk24`).**

| # | Prediction | Result |
|---|---|---|
| 1 | Snapshot top-1 >= 85% at the end-of-ramp probe for stealth 3σ and fast 4σ | **Failed on dev and `cs_long`; mixed on fresh2.** Stealth 3σ at day 85: dev 65%, fresh2 non-network 67%, `cs_long` 77%. Fast 4σ at its own end of ramp (day 70): dev 71%, `cs_long` 76%, **fresh2 non-network 94%** (adaptive 98%). Top-2 at day 85 is 86 to 96% |
| 2 | Adaptive less often first than the snapshot at the last probe by >= 10 points (stealth) | **Holds at 39 and 139 days after the event** (dev day 99: +28 / +43 points, intervals exclude 0; cs_long day 199: +29 / +43). **Does not hold on fresh2** (day 89, 29 days after the event: +1 / -1). At the first probe the adaptive reference is **better** (dev -36 / -33; cs_long -13 / -14), which the prediction did not anticipate |
| 3 | Snapshot flags more non-target metrics than adaptive in the control | **Mostly holds, small**: dev 0.36 / 0.45 / 0.82 against 0.06 / 0.22 / 0.64 per case; fresh2 non-network 0.08 / 0.82 / 0.24 against 0.00 / 0.75 / 0.20; cs_long mixed (0.47 / 0.37 / 0.37 against 0.22 / 0.43 / 0.24) |
| 4 | Measured top-1 below 94.0% on at least one dataset | **Holds on all** (the 94.0% in the target deck is top-3 for a different test; our top-3 for resources with >= 5 metrics is 85 to 100% at the snapshot) |

**What changes in the claim.** The link "attribution runs against the trusted snapshot" has measured value only after the baseline has had time to
absorb the shift (dev day 99, 39 days after the event; `cs_long` day 199, 139 days after). On fresh2, 29 days after the event, the adaptive reference
is as good, and earlier it is better. The link stays a dependent feature (D10), stated with that condition. The snapshot also produces more false attributions in the
control (0.4 to 0.8 non-target metrics flagged per case on dev), which the explanation must report (LOW confidence or UNKNOWN).
