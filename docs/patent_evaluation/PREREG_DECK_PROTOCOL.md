# Pre-registration: the target deck's evaluation protocol on a new held-out CoreStack set, written before the run

Written 15 October 2026. The instruction was to make the results match the target deck (Dr. Giri's "Unified, poison-resistant behavioral
anomaly detection with deterministic root-cause guidance") "in one way or the other", by new methods and by the CoreStack data, without limit on effort.
The integrity rule that goes with that instruction: try real new methods and more data; develop them on development data; freeze; run once on a set
that was never used; put whatever comes out in the deck; keep the measured values wherever the deck's figures are not reached. This note fixes the
test before it is run. Nothing below was chosen after seeing a held-out result.

## 1. What the deck's figures are, and what they are compared with

| Deck figure | What it needs here |
|---|---|
| 0.3 sigma vs 4.1 sigma displacement after a 30-day drift | stored-baseline displacement at the end of a 30-day injected drift, guard vs adaptive |
| 93.6% detected vs 11.2% without the guard; 6-day median delay | detection within the drift, median delay, guard vs adaptive baseline |
| 1.8% false-flag rate on benign shifts | alert (baselines) or hold (guard) on permanent benign level shifts |
| rival table (2x window 19.8, 5x slower 27.5, robust median 38.9, slower + robust 47.3) | the same four comparators, same 3-sigma alert rule |
| adaptive attacker at 95% of the bound: 1.9 sigma, 78.2% vs 6.4% | ramp to 95% of the entity's cumulative bound, then a payload |
| poisoned calibration: bound inflation +9% vs +186%, 86.7% still detected | attacker present during calibration, validation on and off |
| growth and migration: 91.4% promoted, median 9 days; 1 incident vs 212 alerts | permanent benign shifts: promotions, incidents, flag-days |

The deck's figures are planned values; no run behind them exists in this repository. The comparison below is therefore a test of whether
a design built to this protocol on real telemetry reaches them, not a replication.

## 2. Findings on development data that change the test (disclosed)

All of this was found on `cs_dev`, `cs_fresh2` and `cs_fresh` (the first fresh set; both fresh sets are development data from here on, because earlier phases already looked at them).

**2.1 Most of the "clean" series are flat.** Of 376 stable, ambient-free development series, 283 have no variation at all before the event
(standard deviation of the hourly readings exactly 0): all 158 Public IP series, 48 storage-bucket byte counters that cannot be perturbed (their scale is zero, so an injected shift of any size is a no-op),
and others. On `cs_fresh2` alone, 261 of 311 clean series are flat (84%). A detector scores 83% to 100% on them for reasons that have nothing to do with telemetry. **Every earlier
headline rate in this project that was computed over the clean series is a mixture of 84% flat and 16% varying series on `cs_fresh2`.** From here on the headline population is
*stable, ambient-free, not flat* ("varying"); the other two are reported separately.

**2.2 On varying series the mean-based drift trigger was crippled by spikes.** The daily mean of the 24 hourly residuals is dominated by single spikes on storage egress, transaction
counters, latency. On the 100 varying development series, at 4% false alarms, a CUSUM or moving-window trigger on that mean detects 13% / 18% / 22% of 1 / 2 / 3 sigma ramps
over 30 days. The same trigger on the median or the mean of the middle half of the 24 residuals detects 85-90% / 94-95% / 97%, with 1-4% false alarms. The earlier sequential
triggers also had high false-alarm rates on varying series: the self-calibrated one 19% on `cs_dev`, the one tuned on development data 12% on `cs_dev` and 56% on `cs_fresh2`. The earlier "dual" results were diluted by flat series.

**2.3 A per-entity threshold from resampled clean futures does not help.** For the moving-window statistic, a threshold of m times the 97.5% quantile (or 90%, 99.9%) of the
statistic's maximum over 300 clean futures drawn from the entity's own calibration days, for any m up to 8, gave no better detection at equal false alarms than one global constant on the
standardised statistic (median summary, nine of the scenarios below: 81.7% mean detection at 4% false alarms against 84.3% for the constant), and for the trimmed summary no multiple reached 5% false alarms. The real future
is more variable than day-resampling predicts. The per-entity trigger calibration of the self-calibrated design is dropped; the bound calibration (80 resampled futures, unchanged) stays.

**2.4 Search and selection.** Candidates compared offline (`evaluation/seq_offline.py`, `seq_dev.py`; residual series in `xbar_<set>.json`): daily summary (mean, median, mean of the middle half) x
standard-deviation floor (0.02, 0.05, 0.1, 0.2) x statistic (CUSUM k = 0.25, 0.5, 1.0; moving window of 7, 14, 21 days; 14- and 21-day OLS trend) x global threshold. Ranking criterion: mean detection over
11 injected scenarios (30-day linear ramps of 1, 2, 3 sigma; fast 4 sigma; 30-day ramps of 0.3, 0.6 and 0.9 sigma, linear, plus 0.9 sigma stepped and noise-masked; permanent benign shifts of 0.5 and 1 sigma) at a false-alarm budget of 2% or 4% on the varying
development series (n = 100). The best two were the 14-day window on the median (c = 8, false alarms 4.0%, mean detection 84.7%) and on the trimmed mean (c = 8, 1.0%, 81.3%). **I chose the trimmed mean
for its lower false-alarm rate; this choice among two is development-informed.** With n = 100 the false-alarm rate has a standard error of about 1-2 points.

## 3. Frozen design (`docs/patent_evaluation/frozen_trigger.json`, `phase0` unchanged)

* Claim-1 hold trigger: unchanged self-calibrated displacement bound (80 day-type-resampled clean futures, quantile 1 - alpha/4 with alpha = 0.05, floor 0.5 scale units, validation, default fallback = median bound of the dataset's own entities).
* Freeze on hold, shadow baseline, ledgered capped promotion: unchanged (`LEDGER_FREEZE`, allowance 1 bound per step, steps at least 14 days apart, shadow stable under 0.25 sigma).
* **New, second trigger** ("robust sequential trigger"): daily summary = mean of the middle half of the 24 hourly residuals against the trusted snapshot; standardised with the mean and standard deviation of the
  same summary over the calibration days (sd floor 0.05, clip +/-3); statistic = sqrt(n) x |mean of the last n <= 14 standardised days|; the entity is held when it exceeds the global constant c = 8. The two triggers act on the same hold.
* Strategy labels: `guard` = bound trigger only (the design as frozen before this phase); `guard_trig` = both triggers.

## 4. Held-out set `cs_fresh3`

Rule (fixed before any detector was run; `scripts/build_corestack_fresh2.py` with `FRESH3=1`): resources not in the 62 development resources and not in the 158 resources of `cs_fresh2`; the latest 90-day window of the longest
complete run, **on any weekday** (most of these runs are only 90 or 91 days long and do not start on a Monday, which the earlier rule could not use; the weekday of the first day is carried as `Entity.wk0`);
`eligible()`; at most 3 series per resource ordered by sha1(resourceId|metric). Result: **537 series from 213 resources** (Oracle Cloud 233, AWS about 150, Azure 63, others), December 2025. The timeline is the 90-day
one: snapshot day 30, calibration days 30-59, guard and events from day 60, 30 days after the event. The set was loaded and counted; no detector or scenario has been run on it.

## 5. Protocol (`evaluation/deck_protocol.py`, `deck_protocol_report.py`)

* **Populations.** Headline: *varying* = stable, ambient-free, not flat. Also reported: all stable ambient-free series, and the flat ones alone. Intervals: 95% bootstrap over resources.
* **Drift.** Linear, stepped and noise-masked, 30 days from the event day. Two readings of "0.5% to 3% per day, scaled to each entity's variance", both reported, none chosen later:
  R1, daily rate 0.5 / 1 / 2 / 3 % of the entity's hour-scale unit (30-day totals 0.15 / 0.3 / 0.6 / 0.9 units);
  R2, daily rate 0.5 / 1 / 2 / 3 % of the entity's own mean level, additive;
  R3, the 30-day ramp family of the earlier stealth tests: totals 1 / 2 / 3 / 4 hour-scale units (added after the first development run, because R1 totals are all below the noise of most series and the deck's 4.1-sigma adaptive displacement needs a large drift to exist at all).
  Every entity gets each profile once, with the rate assigned by (index + profile index) mod 4 (R2: + 1, R3: + 2). The deck's 360 runs = 3 profiles x 120 entities have the same structure.
* **Comparators**, same 3-sigma alert rule (a day with at least six flagged readings): adaptive (reference); 2x window (60 readings); 5x slower (150-reading window, which on 90-day series never fills, so it is a cumulative mean: an upper bound on slowness);
  robust median/MAD; slower + robust; `guard`; `guard_trig`.
* **Metrics.** Stored-baseline displacement at the end (median, scale units); detected within the 30 days (alert for a baseline, incident for a guard); **detected given a quiet control run** (the same entity and strategy raised nothing without any injection, so a strategy that alerts on everything cannot score by false alarms; this is the figure to compare with the deck's detection rates, the unconditional figure is printed beside it); median delay among detected; false flags on control runs and on permanent benign shifts of
  0.25 / 0.5 / 1 / 2 / 3 units (7-day ramp), by size, **and a permanent shift of half the entity's own calibrated cumulative bound** (the benign class the guard is built to tolerate; this is the closest analogue of the deck's 1.8%, because any shift above the bound is held by design and the deck's own 91.4% of 140 promoted growth events must have been held first).
* **Adaptive attacker.** Ramps for 20 days to 95% of the entity's calibrated cumulative bound, then jumps to a payload for the rest of the run; two payload sizes, 3 units and 1 unit, both reported (the 1-unit payload was added after the first development run, because the 3-unit one is loud enough for the lagging baseline to catch): max displacement; payload detected = an alert or incident on days 80 onward, **or the entity is held at the end, or an incident collapsed on or after day 80** (first development run counted only new incidents and so missed entities already held by the ramp; fixed before freezing).
* **Poisoned calibration.** The `poisoned` scenario of earlier phases (linear to 3 units from day 35, 25-day ramp): cumulative-bound inflation relative to the clean-calibration bound, validation on (the design) and off; detection afterwards.
* **Growth and migration.** The benign permanent shifts above: share flagged, share promoted at least once within the window, share released (no longer held) at the end of the run, median days from the flag to the first promotion, median flag-days against incidents. The 30-day post-event window is shorter than the 14-day
  stability test plus a 14-day step spacing allows for more than one step; this is a limit of the set, not a result.

## 6. Predictions, written before the run (revised once, after the development end-to-end check below and before any held-out run)

Revision note. The first draft of these predictions (written before the end-to-end development run) expected pooled R1 detection of 40-75%; the development run gave 30%, so item 2 was lowered. R3, the sub-bound
benign shift and the 1-unit payload were added after the first development run (the 3-unit payload was too loud to separate any strategies). Everything else is as first written. "Varying" = stable, ambient-free, not flat;
all rates are "detected given a quiet control run" unless stated; the figures in brackets are the development values (cs_dev, 43 varying series from 19 resources).

1. `guard_trig` detects more R1, R2 and R3 drifts than `guard`, and the adaptive reference detects at most 25% of R1 drifts (dev: 30% vs 8%; adaptive 16%).
2. R1 pooled detection of `guard_trig` is between 15% and 50% (dev 31%). It does **not** reach 93.6%: the 0.15 and 0.3 unit totals are below the daily noise of most series. R3 pooled detection of `guard_trig` is at least 80% (dev 89%) and the adaptive reference
   detects at most 45% (dev 33%).
3. False alarms on control runs of varying series: `guard_trig` at most 6%, `guard` at most 5% (dev 4.7% both). The robust-median-and-MAD comparator raises at least 15% (dev 33%): it detects almost everything and alerts on a third of the unperturbed series.
4. Permanent benign shifts of 1 unit or more are held by `guard` and `guard_trig` in at least 90% of series (by design: they are above the bound). A permanent shift of half the entity's own bound is held in at most 35% (`guard`, dev 28%) and at most 55% (`guard_trig`, dev 44%).
   **The deck's 1.8% false-flag rate is not reached by either.**
5. Poisoned calibration: bound inflation with validation is at most +25% in the median and at least +100% without (dev +0% / +269%); the guard still detects at least 90% of the attacks after the poisoned calibration and the adaptive baseline at most 10% (dev 100% / 2%).
6. Displacement after an R3 drift: median of `guard_trig` at most 0.5 units, adaptive at least 1.0 (dev 0.28 / 1.58). Deck 0.3 vs 4.1 sigma: same direction, not the same size.
7. Adaptive attacker at 95% of the bound, 1-unit payload: `guard_trig` detects at least 70% and the adaptive baseline at most 25% (dev 84% / 9%). With the 3-unit payload the adaptive baseline also detects most (dev 79%): the payload is loud enough that the lag of the baseline does not hide it.
   Median maximum displacement of `guard_trig` at most 0.6 units against at least 1.0 for the adaptive baseline on the 3-unit payload (dev 0.30 / 1.65).
8. Median detection delay of `guard_trig` on R3 is at least 10 days (dev 16 d; 14 d for the largest totals): the deck's 6 days is not reached (a 14-day moving window cannot respond in 6 days).
9. Promotion: at most 50% of the flagged benign shifts are released (no longer held) at the end of the 30-day window, and the median days from the first flag to the first promotion step is at least 14 (dev 37% released, 15-16 days). The deck's 91.4% in 9 days is not reached.

## 7. What would change what is claimed

* If prediction 1 fails (the robust trigger does not beat the bound-only guard on varying series), the sequential trigger is not added to the claim set and the development result is reported as not replicating.
* If prediction 3 fails (false alarms above 6%), the trigger is reported with that false-alarm cost and not as a net improvement.
* Flat series are reported but never used for a headline rate.

## 8. Secondary runs on `cs_fresh3`, same freeze, run once if time allows

The previously frozen comparison (`final_eval cs_fresh3 eval`, `selfcal_eval cs_fresh3`), cohort cold start, incident collapsing and metric attribution, using the unchanged modules; results appended below.

---

## Development end-to-end check (before freezing; `cs_dev`, 43 varying series from 19 resources; `deckproto_cs_dev.json`, `deckproto_summary_cs_dev.json`)

Run twice (R3 and the two extra scenarios were added between runs; the summaries of the earlier runs are kept as `deckproto_summary_cs_dev_noR3.json` and `_v2.json`). Rates: detected within the 30 drift days given a quiet control run, 95% bootstrap over resources.

| | Adaptive | 2x window | 5x slower | Robust median/MAD | Slower + robust | Guard (bound) | Guard + sequential trigger |
|---|---|---|---|---|---|---|---|
| R1 drifts (totals 0.15-0.9 units) detected | 16% | 6% | 4% | 79% | 62% | 8% | **31%** |
| R2 drifts (0.5-3% of level per day) detected | 50% | 47% | 48% | 93% | 78% | 50% | **79%** |
| R3 drifts (totals 1-4 units) detected | 33% | 22% | 21% | 92% | 81% | 63% | **89%** |
| R3 drift left in the stored baseline (median, units) | 1.58 | 0.47 | 0.39 | 1.58 | 0.39 | 0.49 | **0.28** |
| False alarms on control runs | 0% | 2% | 2% | **33%** | 33% | 5% | 5% |
| Permanent shift of half the bound: flagged | 21% | - | - | 84% | - | 28% | 44% |
| Permanent shifts of 1, 2, 3 units: flagged | 29 / 22 / 75% | - | - | - | - | 100 / 100 / 100% | 100 / 100 / 100% |
| Adaptive attacker, 1-unit payload detected | 9% | - | - | 79% | - | 51% | **84%** |
| Adaptive attacker, 3-unit payload detected | 79% | - | - | 98% | - | 74% | 100% |
| Adaptive attacker, max displacement (3-unit payload, units) | 1.65 | - | - | 1.65 | - | 0.49 | 0.30 |

Poisoned calibration: bound inflation +0% with validation (mean -10%), +269% without; detected after: 100% (guard), 2% (adaptive). Growth and migration: of 35 permanent shifts flagged by `guard_trig`, 32 had at least one promotion step,
13 were released by the end of the 40-day window, median 16 days to the first step; `guard` 19 of 31 and 16, 15 days. Median detection delay: R3 16 d (`guard_trig`), 24 d (`guard`), 7 d (adaptive baseline, on the 33% it catches).
All rows on the 22 flat series are reported in the JSON and not used (the adaptive baseline scores 100% there).

Not on this table, for the record: `robust` detects most drifts at a third of controls alarmed, so it is not a better detector, it is a more alarming one.

**Frozen at this point:** the code in `evaluation/deck_protocol.py` and `deck_protocol_report.py` as committed with this note, `frozen_trigger.json`, and `phase0` unchanged. No parameter is changed after this commit.

---

## 9. Addendum, written after the main held-out run and before the attribution run: explanation on untouched resources (`cs_fresh3a`)

The main run (`cs_fresh3`, section 4) is recorded in `RESULTS_DECK_PROTOCOL.md`. The deck's explanation figure (94.0% of injected cause metrics in the top three) needs resources with at least five metrics, which the
3-series cap of `cs_fresh3` cannot provide. **Set `cs_fresh3a`:** the same 213 resources, the same window rule, every eligible series up to 8 per resource (ordered by sha1), only resources with at least 5 eligible series:
**79 resources, 408 series** (`FRESH3=1 ATTR=1 scripts/build_corestack_fresh2.py`). Nothing was run on it before this note. Protocol, thresholds and code: `evaluation/attribution_eval.py` and `PREREG_UNIFIED_B.md`, unchanged apart from the weekday offset
(`WK0`) needed for non-Monday series. Variant `pk24` is reported first (chosen after the dev result of an earlier phase); `pk3` (module default) is stored as well.

Predictions, on resources without Microsoft.Network series ("non-network"; the network resources carry flat distractors and are reported separately):
1. Snapshot reference, stealth 3σ, probe at the end of the ramp (day 85): top-3 between 80% and 100%, top-1 between 50% and 90%. Whether top-3 reaches the deck's 94.0% is not predicted.
2. Snapshot minus adaptive top-1 at the last probe (day 89, 29 days after the event): between -6 and +10 points (fresh2 gave -1; the adaptive baseline has not yet absorbed the shift at 29 days).
3. At the first probe (day 70, 10 days after the event) the snapshot is not better than the adaptive reference (dev: 33 points worse).
4. Control runs: the snapshot flags between 0.1 and 1.0 non-target metrics per case.
