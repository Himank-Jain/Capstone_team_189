# Third-party data: what was tried, what was downloaded, what it shows

Permission to download public data for this purpose was given by the project owner in the chat of 15 October 2026. Every download is
listed here with source, files and size. Nothing downloaded is committed (`scripts/fetch_smd.sh` fetches it again); only results are.

## Result in one paragraph

No public dataset of **baseline poisoning** was found or reachable, so the claim that matters most (the stored baseline resists a slow
adversary) still rests on attacks written by us or implemented by us from papers (`SELFCAL.md`). What could be fetched is real, third-party
**operational incident** data: the Server Machine Dataset (28 internet-company servers; operators labelled the incidents and the metrics
involved). On 8 machines (236 metric series, 193 labelled incident-metric events) the guarded baseline detects incidents about as often as
the unguarded adaptive baseline (46% against 42%, wide overlapping intervals) and leaves 31% of series held at the end of the run. That is a
non-regression check on third-party data, not evidence for the poisoning claim, and the series are too short to exercise promotion.

## What was tried and what the network allowed

The session reaches the internet only through an egress policy proxy. Tested and **refused (policy denial, not retried or worked around)**:
kaggle.com, data.mendeley.com, zenodo.org, figshare.com, archive.org, huggingface.co, osf.io, drive.google.com, dataverse.harvard.edu,
researchportal.hw.ac.uk, gitlab.com, bitbucket.org, s3.amazonaws.com, storage.googleapis.com, sourceforge.net, unpkg.com, cdn.jsdelivr.net;
github.com pages, codeload.github.com and api.github.com (403: sessions are bound to their configured repositories). Reachable:
raw.githubusercontent.com (files in public repositories), pypi.org and the package registries.

So these candidates could **not** be fetched: the Kaggle cryptojacking attack time series, the TSD-DDoS dataset (Mendeley), the IEEE
DataPort time-series DDoS dataset, the SI22 DoS-on-cloud dataset, and HAI (needs `git clone` and Git LFS; it is also 1 Hz industrial-control
data over a few days, which does not fit an hourly, 60-day protocol). If the owner downloads any of these from a browser (the Kaggle ones need
a login that the assistant must not use) and attaches the files, they can be run through the same harness.

## What was downloaded

| Item | Source | Files | Size |
|---|---|---|---|
| Server Machine Dataset, machines `machine-1-1` to `machine-1-8` | `raw.githubusercontent.com/NetManAIOps/OmniAnomaly/master/ServerMachineDataset/` (Su et al., "Robust Anomaly Detection for Multivariate Time Series through Stochastic Recurrent Neural Network", KDD 2019; MIT-licensed repository) | `train/`, `test/`, `test_label/`, `interpretation_label/` per machine (32 files) | 128 MB |

Each machine has 38 metrics at one reading per minute for 33 to 40 days. The first half has no labels; operators labelled incident segments in the
second half and listed the metrics each incident involved.

## How it was run (`evaluation/third_party_smd.py`)

Hourly means of the real, chronological series; nothing injected, resampled or re-ordered. The design is the frozen self-calibrated design with
nothing tuned on this data: bound from the entity's own calibration days (40 resampled futures, alpha 0.05), default bound = median own bound.
**Protocol compressed** because the series are 33 to 40 days (profile `smd` in `scenarios.py`): snapshot after 8 days, calibration days 8 to 14,
guard active from day 15, run ends at day 32. Variants: adaptive baseline; H (hold only); full (the design, freeze on hold); full_B (partial hold).
Events counted: labelled segments of at least 60 minutes (shorter ones vanish in hourly means) that involve the metric, starting after day 15
(193 on 7 machines). A "clean" day is one with no labelled minute on the machine within a day either side.

## Results (8 machines; bootstrap over machines, so intervals are wide)

Alert = a z-flag day or a guard incident (what a deployed system raises; the guard adds incidents to the ordinary alerts):

| Variant | False alert on unlabelled days | Alert days per unlabelled day | Labelled events detected | Held at end of run |
|---|---|---|---|---|
| adaptive baseline | 34% (0-77) | 4% (0-8) | 42% (19-68) | 0% |
| hold only (H) | 38% (0-90) | 6% (0-15) | 46% (22-71) | 31% (14-50) |
| **full design** | 38% (0-90) | 6% (0-15) | 46% (22-71) | 31% (14-50) |
| full, partial hold | 38% (0-90) | 6% (0-14) | 45% (22-70) | 31% (13-49) |

Incident only (the convention of `final_eval.py`; adaptive = z-flag days): guard variants 21% (0-60) false alerts and 8% (0-25) of events
detected, against 34% and 42% for the adaptive baseline. The self-calibrated bound is the 0.5σ floor for 11% (5-16) of these series.

## What this does and does not show

* **Does not show the poisoning claim.** These are incidents, not baseline poisoning and not security attacks.
* **Does show no gain and no loss in incident detection** (46% against 42%; the intervals overlap broadly, 8 machines). The guard alone, without the
  z-score alerts, detects 8%: it is a slow-drift mechanism, not an incident detector, as designed.
* **Cost, visible on third-party data:** 31% of series end the run held, because a hold cannot resolve inside the horizon (a shadow needs about
  28 days) and operators have not acted. On real incidents that move a metric's level the design therefore leaves the entity frozen and alerting.
* **False alerts are high for every strategy on this data** (34% to 38% of series have an alert on a day with no labelled incident nearby). Labels are
  incomplete (unlabelled incidents exist, so this is an upper bound) and the 8-day snapshot is thin: weekend buckets get fewer than 5 readings and are
  unmonitored. The design has not been shown to work with so short a history.
* **Promotion is not exercised** (one step needs about 28 days after a hold), and the calendar is unknown (the first day is treated as a Monday).
* Only 8 of 28 machines; the machines differ in length, so the run ends at day 32 and later incidents are not used.
