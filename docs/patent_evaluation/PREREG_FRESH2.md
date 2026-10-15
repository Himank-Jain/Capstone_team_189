# Pre-registration: second fresh CoreStack evaluation ("fresh2")

Written and committed **before any detector was run on these series**. After this commit nothing about the data selection, the
designs, the scenarios or the metrics is changed. Anything that does change is listed in "Deviations" at the bottom, with the
reason, and the result is reported with the deviation attached.

## 1. Data

* Source: the raw CoreStack daily-collection dump (9,048,129 documents), read on the owner's machine.
* Series: one hourly series per (resource, metric) pair that has at least 90 consecutive days with all 24 hourly values.
  Value = the `average` field. 3,738 pairs qualified; 2,194 had a complete hourly run of 90 days or more.
* Selection rule (`scripts/build_corestack_fresh2.py`, fixed before any detector ran):
  1. the resource is not one of the 62 resources already used (development: 37, first fresh set: 25);
  2. the latest Monday-aligned 90-day window inside the run;
  3. `evaluation.runner.eligible()` accepts the series (the same non-degenerate-scale filter every other set uses);
  4. at most 3 series per resource, taken in order of `sha1(resourceId|metric)`.
* Result: **158 resources, 336 series**. Before this commit the only things computed on them were the ordinary baseline's
  z-flags (the "ambient-free" test) and the maximum level shift (the "stable" test), to count the groups below. No result of
  any evaluated design was looked at.

| Group | Series | Resources |
|---|---|---|
| Clean (stable and ambient-free) | 311 | 148 |
| Real shifts (>= 1 scale unit) | 18 | 13 |

* By category the clean group is 157 Public IP address series, 48 bucket, 43 storage account, 12 disk, 11 automation account,
  10 SQL database, 10 app-service plan, 6 virtual machine, and 14 others. Results are also reported without Public IP series.
* Caveat. The series come from the same customer dump as the development set, so they are new resources, not an independent
  deployment. The bootstrap resamples whole resources. The extraction rule was re-implemented for this set; it reproduces 164
  of 239 earlier derived series exactly and the rest on at least 90% of their hours.

## 2. Designs run

* **A, tuned design.** Frozen at commit `9c892e5`: thresholds tuned on development data to at most 5% false alerts, cohort
  statistics from development. Run unchanged.
* **B, self-calibrated design** (`evaluation/margin_rule.py`, `evaluation/selfcal_eval.py`). No threshold is tuned on any
  dataset. For each entity at the end of its calibration period: resample its own calibration days (same day type, with
  replacement) into 80 clean futures, run the unmodified baseline on each, and set the displacement bound to the 98.75th
  percentile (1 - 0.05/4) of the largest displacement seen after the calibration period. Validation (alert exclusion and
  split-half trend below 0.5 scale units) and the default fallback are unchanged; the fallback is the median
  self-calibrated bound of the dataset's own entities; the floor is the fixed 0.5 scale units. Variants:
  * `B`: partial hold (readings that individually stay inside the bound still enter the window, as in the tuned design);
  * `Bf` (**the design under test**): the entity freezes at the first breach, every later reading goes to the shadow,
    promotion is capped and ledgered as before.
* Not run on fresh2, because development data showed them to fail: the cohort p95 cross-check and 1.5x cap on top of a
  self-calibrated bound (false alerts 15% against a 5% target) and a self-calibrated sequential trigger (14%).

## 3. Scenarios

control, stealth 1, 2 and 3 sigma (20-day ramp), fast 4 sigma (10 days), local 4 sigma (business hours), poisoned calibration,
benign growth (as in `final_eval.py`); plus two attacks specified in the literature and implemented by us:

* `frog g` for g = 1.01, 1.02, 1.05, 1.15: the attacked metric's average level grows by g every week (Rubinstein et al., IMC
  2009, "boiling frog"; those are the growth rates they report). Included when the final shift is 1 to 100 scale units.
* `greedy`: every injected reading is placed at the edge of the deployed z-score detector's acceptance region (z = 2.9
  against the threshold of 3) until the stored baseline has moved 6 scale units (Kloft and Laskov, JMLR 2012, greedy
  attack on an online centroid detector). Included when it reaches its goal against the unprotected adaptive baseline.

These are **not** third-party attack data; they are other people's attack strategies implemented by us.

## 4. Metrics and reporting

* Rates on clean entities, with 95% intervals from a bootstrap over whole resources; n is reported as series and resources.
* False alerts on control; detection of each attack within its window; silent displacement at the first alert; stored
  displacement at the end; for greedy, the share that reached the goal; legitimate growth and real shifts flagged and
  unresolved.
* The target for the false-alert rate is 5%. Whatever it turns out to be is reported.
* Each design and each scenario is run once. No tuning, no re-run with different settings.

## 5. What would count against the self-calibrated design

* False alerts on clean entities above 10%, or an interval that excludes 5% from above.
* Detection of the 2 and 3 sigma stealth attacks no better than the tuned design at the false-alert rate each achieves.
* Real shifts and legitimate growth left unresolved more often than the tuned design (a cost already seen on development
  data: 65% against 70% unresolved for real shifts, 50% against 25% for legitimate growth).
* The greedy attacker reaching its goal in more than 25% of entities.

## Deviations

(none yet)
