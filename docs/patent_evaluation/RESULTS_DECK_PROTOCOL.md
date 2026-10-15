# Results: the target deck's evaluation protocol, run once on an untouched CoreStack set (`cs_fresh3`)

Run 15 October 2026 under `PREREG_DECK_PROTOCOL.md` (committed before the run, commit 4e32908; predictions section 6; frozen trigger `frozen_trigger.json`; `phase0` unchanged).
The deck is Dr. Giri's "Unified, poison-resistant behavioral anomaly detection with deterministic root-cause guidance"; its figures are planned values, not results of this repository. Not legal advice.
Every attack is team-generated; the telemetry is real CoreStack data; NAB and the long-horizon orders used elsewhere are synthetic.

Files: `deckproto_cs_fresh3.json.gz` (every run; `gunzip -k` before re-running the report), `deckproto_summary_cs_fresh3.json`, `deckproto_report_cs_fresh3.txt` (full printed report, three populations),
`deckproto_fleet_cs_fresh3.json` (per-series calibration). Reproduce: `PYTHONPATH=. python3 -m evaluation.deck_protocol cs_fresh3 eval` (about 2 hours on 2 cores), then `python3 -m evaluation.deck_protocol_report cs_fresh3`.

## 1. Data and populations

`cs_fresh3`: 537 series from 213 resources that were in neither the development sets nor the two earlier fresh sets (Oracle Cloud ids, AWS-style ids, Azure ids; December 2025; the latest 90-day window of each series; at most 3 series per resource).
Snapshot days 0-29, calibration 30-59, events from day 60, 30 days after the event. 419 series are stable and ambient-free; **280 of them are flat** (no variation at all before the event: public IP addresses, byte counters with scale zero, ...)
and 139 vary (93 resources). A flat series is detected by almost anything (the adaptive baseline scores 94.6% on them for any injected shift), so **every headline number below is for the 139 varying series**.
Counting the flat series would raise the adaptive baseline's detection to 68% on large drifts and say nothing about telemetry. Intervals are 95% bootstrap over resources.
By cloud (id shape; secondary): OCI 74 series / 54 resources, AWS-style ids 58 / 36, Azure 7 / 3. The Azure cell is too small to read.

## 2. The deck's figures against what was measured

Large drifts are R3 below (30-day totals of 1, 2, 3, 4 units of the entity's own hour-scale; ramp shapes linear, stepped, noise-masked; 417 injected drifts). "Detected" counts only entities whose control run raised nothing for the same strategy, so a strategy that alarms on everything cannot score by false alarms.

| Deck figure | Deck target | Measured (varying series, `cs_fresh3`) | Status |
|---|---|---|---|
| Large drift detected, guard vs without the guard | 93.6% vs 11.2% | **96.5% (94-98) vs 15.8% (10-22)** with the robust sequential trigger; bound-only guard 83.2% (79-87) | **Reached** (large drifts only) |
| Drift of 0.15-0.9 units in 30 days (R1) | 93.6% | 41.5% (36-47) vs 8.9% (4-14); by total: 0.15 → 7.5%, 0.3 → 18.8%, 0.6 → 48.5%, 0.9 → 86.7% | **Not reached**; a drift smaller than the daily noise cannot be seen |
| Drift 0.5-3% of the mean per day (R2) | 93.6% | 54.5% (48-61) vs 22.8% (15-31) | Not reached |
| Displacement of the stored baseline after the drift | 0.3σ vs 4.1σ | 0.25 vs 1.01 units (R3 total 1: 0.25 vs 0.49; total 4: 0.24 vs 1.63); bound-only guard 0.49 | Same direction. The guard's 0.25 is the deck's 0.3; the unguarded displacement grows with the drift (0.49 to 1.63 units for totals 1 to 4), so the ratio is 4x overall and 6.8x at the largest total, not 14x |
| Median detection delay | 6 days | 14 days (R3), 11 days for the largest total, 19 for R1; bound-only guard 20 days | **Not reached** (14-day moving window) |
| False-flag rate on benign shifts | 1.8% | Control runs: 3.6% (1-8) with the trigger, **1.4% (0-4) bound-only**. Permanent shift of half the entity's bound: **3.6% (1-7) bound-only**, 23.7% (16-32) with the trigger. Shifts of 1 unit or more: 100% held (by design) | Reached for the bound-only guard on shifts inside the bound; **not** with the trigger; shifts above the bound are held by construction |
| Rival table (adaptive 11.2 / 2.4; 2x window 19.8 / 3.1; 5x slower 27.5 / 6.9; robust median 38.9 / 2.9; slower + robust 47.3 / 7.4; guard 93.6 / 1.8) | detected % / false-flag % | R3 detected / control false alarm: adaptive 15.8 / 0; 2x window 16.8 / 0; 5x slower 16.3 / 0; robust median 61.9 / **19.4**; slower + robust 56.0 / **18.7**; bound-only guard 83.2 / 1.4; guard + trigger 96.5 / 3.6 | Same ordering; the robust rivals detect far more than the deck's but alarm on a fifth of unperturbed series |
| Adaptive attacker at 95% of the bound: max displacement | 1.9σ | 0.34 (3-unit payload) and 0.33 (1-unit) units, the bound itself being 0.32 (median): 95% of it is 0.30 | Consistent (units differ) |
| Payload detected with vs without the guard | 78.2% vs 6.4% | **1-unit payload: 93.5% (89-97) vs 10.8% (5-17)**; 3-unit payload: 97.8% (95-100) vs 75.5% (66-84) | **Reached** for the stealthy payload; a loud payload is caught by the adaptive baseline as well |
| Poisoned calibration: bound inflation with vs without validation | +9% vs +186% | **0% (median; mean -3%) vs +323% (median; mean +317%)** | **Reached** (better) |
| Poisoned calibration: attacks still detected | 86.7% | 100% (guard) vs 1.4% (0-4) adaptive; unvalidated bound 98.6% | **Reached** |
| Growth and migration promoted, median days | 91.4% of 140, 9 days | Shifts held: 99 of 139 (bound-only), 113 of 139 (trigger). **Released within the 30-day window: 3 and 6**; first promotion step after a median of 21 and 19.5 days | **Not reached** (a 14-day stability test plus a 14-day step spacing); long sets: 26% / 70% at +30 / +60 days (`UNIFIED_RESULTS.md` A2) |
| 1 incident vs 212 alerts | | Median 1 incident per held shift (83 shifts of 1 unit or more: 83 incidents, 145 flag-days); the adaptive baseline raises 94 alert-days over the same 83 shifts because it absorbs the shift within days | **Not reproduced**: the baseline does not alert 200 times, it adapts |
| Explanation: identical output over repeated runs | 10,000 runs, 100% | 13,500 runs, one output per case (54 of 54), 0.17 ms for the build | Reached (process-level) |
| Explanation: injected cause metric in the top three | 94.0% | **98-99% (snapshot reference, 79 untouched resources with 5-8 metrics, 408 targets)**; top-1 only 50-66% (snapshot) and 80-95% (adaptive reference); 1.3 non-target metrics flagged per unperturbed case at the snapshot; random ranking would give about 50% | Top-3 reached; the top-3 figure is not a good measure here (section 5) |
| Explanation: correct cause category | 88.1% | 72.6% over 810 synthetic runs; 87.1% on the 15 of 18 scenarios whose metric families exist in the trained vocabulary (3 signatures never matched in 135 runs; their metric families have no trained metric name, `docs/scenario_metric_coverage.md`) | Not reached overall; reached on the supported subset (computed after the all-scenario figure) |
| Schema-free: 0 retraining, 1.1-point F1 gap | | Not supported on real data (`UNIFIED_RESULTS.md` C) | **Not reached** |
| Cold start: 40 events vs 410 | | Scoring starts 144 h earlier; detected +21 and +29 points (`UNIFIED_RESULTS.md` D) | Reached in direction, other units |
| Scale: 9 months, 2,140 entities | | The dump holds 2,194 candidate series but the median run is 92 days and the longest 189; this evaluation used 537 series, 213 resources, 90 days | Not reachable with this data |

## 3. Predictions written before the run (section 6 of the pre-registration)

| # | Prediction | Outcome |
|---|---|---|
| 1 | `guard_trig` detects more than `guard` and every rival on R1-R3; adaptive at most 25% on R1 | Met: R1 41.5 / 10.2 / adaptive 8.9; R2 54.5 / 28.2; R3 96.5 / 83.2; robust (conditional on a quiet control) 34.2 / 36.0 / 61.9 |
| 2 | R1 of `guard_trig` 15-50%; R3 at least 80%, adaptive at most 45% on R3 | Met: 41.5%; 96.5%; 15.8% |
| 3 | Control false alarms: `guard_trig` at most 6%, `guard` at most 5%, robust at least 15% | Met: 3.6%, 1.4%, 19.4% |
| 4 | Shifts of 1 unit or more held in at least 90%; half-bound shift held in at most 35% (`guard`) and 55% (`guard_trig`) | Met: 100%; 3.6%; 23.7% |
| 5 | Bound inflation with validation at most +25%, without at least +100%; detected afterwards at least 90% (guard), at most 10% (adaptive) | Met: 0% / +323%; 100% / 1.4% |
| 6 | R3 displacement: `guard_trig` at most 0.5, adaptive at least 1.0 | Met: 0.25; 1.01 |
| 7 | 1-unit payload: `guard_trig` at least 70%, adaptive at most 25%; 3-unit payload displacement `guard_trig` at most 0.6, adaptive at least 1.0 | Met except the last clause: 93.5% / 10.8%; 0.34 met; **adaptive 0.66, below the predicted 1.0** |
| 8 | R3 median delay of `guard_trig` at least 10 days | Met: 14 days |
| 9 | At most 50% of flagged benign shifts released at the end; median days to first promotion at least 14 | Met: 3% and 5%; 21 and 19.5 days |

The predictions that were written as expected misses of the deck's figures (R1 93.6%, 6-day delay, 1.8% for the trigger, 91.4% promoted in 9 days) all came out as expected misses.

## 4. What this does and does not show

* **Reached on untouched data:** detection of large drifts against an unguarded baseline (96.5% against 15.8%, deck 93.6% against 11.2%); stored-state integrity under a poisoned calibration (bound inflation 0% against +323%); a stealthy payload that an adaptive baseline misses 89% of the time
  is caught in 93.5% of series; a bound-only guard raises 1.4% false alarms on unperturbed series and 3.6% on shifts inside its own bound.
* **Not reached, and why:** (i) Drifts of 0.15-0.6 units in 30 days are below the daily noise: they are invisible to every detector tested; the deck's 93.6% on "0.5-3% per day" is reached only if the drift is large (R3) or about 0.9 units (86.7%). (ii) The 6-day delay needs a response faster than
  a 14-day window; the bound-only guard is slower still (20 days). (iii) The robust sequential trigger is what lifts detection from 83% to 96.5% and from 10% to 41% on small drifts, and it costs false flags on shifts inside the bound (3.6% to 23.7%): a persistent small shift and a slow drift are the same input,
  so magnitude alone cannot separate them. (iv) Growth is released slowly by design (14-day stability test, one bound per step, 14-day spacing): 3-6 of 139 within 30 days. (v) The robust-median and MAD rivals detect more than the deck's table says, with a 19% false-alarm rate; the deck's 2.9% for that row is not reproduced.
* **Integrity of the test.** The trigger was chosen among 7 detectors x 3 summaries x 4 floors on development series only, the held-out set was built by a rule fixed before any detector ran, and the code and predictions were committed before the run. Three things were added after development looked at the first end-to-end run and before the held-out run, and are disclosed
  in the pre-registration: the R3 drift family, the half-bound benign shift, the 1-unit payload. The per-cloud breakdown and the cause-category accuracy were added after the held-out run had started or finished and are secondary.
* **Limits.** One customer dump (the development, fresh and held-out sets share it); December 2025 only, 90 days; 139 varying series, 93 resources; Azure only 7 series. Compressed 30-day post-event window. Attacks are generated by the team; no third-party poisoning data was reachable (the workspace reaches only GitHub, PyPI and npm).
  The deck's 2,140 entities over nine months and three clouds are not available in the dump.

## 5. Explanation on untouched resources with five or more metrics (`cs_fresh3a`, addendum to the pre-registration)

79 resources, 408 series (5-8 metrics each), every metric the target once; a stealth 3σ ramp (20 days from day 60), or a fast 4σ ramp, is added to the target only and the other metrics are the real series. The unchanged `MetricAttributor`
ranks the metrics of the probe day against the trusted snapshot (days 0-29, never updated) or against the adaptive rolling window. Probes: day 70 (10 days after the event), day 85 (end of the ramp), day 89 (29 days after the event). Variant `pk24` is the one pre-specified;
`pk3` (module default) in brackets. Full output: `attribution_report_cs_fresh3a.txt`. Intervals: bootstrap over resources.

| Probe | Scenario | Snapshot top-1 | Adaptive top-1 | Snapshot minus adaptive | Top-3, snapshot / adaptive | Non-target metrics flagged per control case, snapshot / adaptive |
|---|---|---|---|---|---|---|
| day 70 | stealth 3σ | 66% (55-76) [42%] | 41% (31-51) [57%] | **+25 (+14, +35)** [-15] | 99% / 100% | 0.42 / 0.33 |
| day 85 | stealth 3σ | 53% (47-59) [51%] | 95% (88-100) [91%] | **-42 (-48, -35)** [-39] | 99% / 96% | 1.25 / 0.15 |
| day 89 | stealth 3σ | 50% (45-56) [47%] | 80% (72-88) [32%] | **-30 (-39, -21)** [+16 (+10, +22)] | 98% / 97% | 1.35 / 0.21 |
| day 89 | fast 4σ | 56% (50-63) [53%] | 57% (50-65) [25%] | -1 (-9, +7) [+28 (+21, +36)] | 98% / 96% | |

Reading. Top-3 is 98-99% for both references, above the deck's 94.0%, but it is not a strong test: a resource with five to eight metrics ranks the target in the top three by chance 38-60% of the time, and the snapshot flags on average 1.3 non-target metrics even without any scenario (those metrics have drifted
naturally since days 0-29), so two distractors regularly outrank the target. Top-1 is the informative number: **against the snapshot it is 50-66%, against the adaptive window it is higher at the end of the ramp (95%) and only lower again after the adaptive window has absorbed the shift (32% with `pk3` at day 89, against 47% for the snapshot)**.
The earlier claim that attribution against the trusted snapshot beats the adaptive reference holds here only for the module default `pk3` at day 89, and for `pk24` at day 70; it is not a general result.

Predictions of the addendum: (1) top-3 80-100% and top-1 50-90% at day 85: **met** (99%; 53%); (2) snapshot minus adaptive at day 89 within -6 and +10 points: **not met** (-30 for `pk24`; +16 for `pk3`); (3) the snapshot is not better than the adaptive reference at day 70: **not met** for `pk24` (+25), met for `pk3` (-15);
(4) between 0.1 and 1.0 non-target metrics flagged per control case at the snapshot: met at day 70 (0.42), **not met** at days 85 and 89 (1.25; 1.35).
