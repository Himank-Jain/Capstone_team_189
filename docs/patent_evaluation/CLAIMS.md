# Candidate claims, technical effect and evidence status (revised 15 October 2026)

Working draft for the patent attorney. Not legal advice. Numbers are from `FINAL_TABLES.md` (frozen design at commit `9c892e5`,
5% target false-alert rate; "dev" = development data, "fresh" = data never run before the freeze). Component results are in
`ABLATION.md`, the bound on promotion in `GUARANTEE.md`, prior art in `PRIOR_ART.md`.

## 1. What the invention is

A monitoring system that keeps, for each monitored entity, a trusted baseline snapshot and a live adaptive baseline, derives a
displacement bound from a **validated** calibration period, and **holds** the live baseline when the bound is exceeded.
Separately, a held baseline is not discarded: a shadow baseline learns during the hold and is promoted in capped steps, each
recorded in a ledger with a restore point.

## 2. Technical problem and effect (the wording to defend)

* **Problem.** A baseline that always adapts can be rewritten by a slow adversary, or by a poisoned calibration period, before
  anyone is alerted. A baseline that never adapts leaves real change alerting for ever.
* **Effect 1 (claim 1): the stored baseline is protected from a poisoned start.** Poisoned calibration is caught in 98% of runs
  on CoreStack dev (95% interval 95–100) against 66% for clipped CUSUM, 60% frozen and 2% adaptive; 100% on NAB dev and fresh
  (adaptive 9% and 35%). Validation ablation (earlier run): 21 of 21 held-out NAB entities with validated bounds against 1 of 21
  without; 39 of 39 against 28 of 39 on CoreStack.
* **Effect 2 (claim 2): real change resolves and every step is recorded.** Of the real shifts each strategy flags in fresh
  CoreStack data (41 series, 16 resources), the proposal resolves 42% (95% interval 19–62) against 7% for clipped CUSUM (0–21)
  and 0% for frozen and rollback. Legitimate growth injected into NAB: unresolved 6% dev and 0% fresh against 80–88% for frozen
  and clipped CUSUM. Every step has a ledger entry and a restore point (unit-tested, no field data).
* **A stated bound on promotion.** Each step moves the baseline by at most an allowance, and steps are at least 14 days apart
  (`GUARANTEE.md`). At the tuned settings this limits shifts larger than about 4σ per 14 days; it does not stop a 3σ attack.
* **Cost.** False alerts on clean dev entities are 10% (NAB) and 8% (CoreStack) against the 5% target.
* **Not claimed.** That attacks are never absorbed. A persistent attacker level looks like persistent growth; by +60 days after
  the first alert the median share absorbed is 1.0 on NAB. Detection of stealth attacks equals clipped CUSUM and does not beat
  it. Rollback absorbs less of an attack than the proposal and resolves less growth: different point, not above it.

## 3. Draft claims

### Independent claim 1: validated calibration and hold

> 1. A computer-implemented method of maintaining a behavioural baseline for a monitored entity in a monitoring system, comprising:
> (a) storing for the entity a trusted baseline snapshot and a live baseline updated from incoming readings;
> (b) deriving from readings of a calibration period a displacement bound for the entity, and validating the calibration period
> before the bound is used by at least one of excluding readings in an alert period, testing the calibration readings for a trend,
> and comparing the entity's calibration statistics with those of a cohort of entities, wherein, when validation fails, a default
> bound is used instead of a bound derived from the calibration readings; and
> (c) when the displacement of the live baseline from the trusted snapshot exceeds the bound, changing the entity from an update
> state to a hold state in which incoming readings are no longer applied to the live baseline.

### Independent claim 2: shadow, capped promotion and ledger (not dependent on claim 1)

> 11. A computer-implemented method for a monitoring system that holds a live baseline of a monitored entity against updates,
> comprising: storing incoming readings during the hold in a shadow baseline; promoting the shadow baseline into the live
> baseline only after the shadow baseline has met a stability criterion for a minimum period, a displacement applied by one
> promotion being limited to an allowance; and storing for each promotion a ledger record and a restore point of the live
> baseline taken before the promotion, so that the promotion can be reverted and the readings it affected re-scored.

Add a system claim and a computer-readable-medium claim for each, in the same words. Word the claims around stored system state
and operations (store, validate, hold, shadow, promote, record, restore) and the measured integrity effect.

## 4. Dependent claims and evidence status

| # | Dependent feature | Depends on | Evidence | Status |
|---|---|---|---|---|
| 2 | Default bound is a cohort-derived bound; bound = multiple of the entity's own 99th-percentile calibration drift, multiple tuned on separate series | 1 | tables; m = 9.92 NAB, 6.3 CoreStack | supported, but m differs by dataset (see weaknesses) |
| 3 | Cohort cross-check and cap on the bound; split-half trend test; alert-period exclusion | 1 | validation ablation 21/21 vs 1/21 | supported |
| 4 | Per-bucket bound floor; weekday and weekend coherent shift statistic | 1 | regression tests | supported |
| 5 | Second trigger: a sequential detector on the residual against the snapshot also causes the hold; each trigger given half the false-alert budget; residual clipped | 1 | dual vs single trigger: 2σ stealth 8% to 94% on NAB dev, 14% to 68% on CoreStack dev | supported on dev; CoreStack half-budget not reachable (floor about 8%) |
| 12 | Revert of a promotion and re-score of the readings it made normal | 11 | unit tests | implemented, no field data |
| 13 | Promotion steps at least the shadow period apart; step size at most a stated allowance | 11 | `guarantee_check`: 715 steps, 0 violations | supported |
| 14 | Episode continuity after a capped step | 11 | unit tests | implemented |
| 15 | *Optional:* allowance increased by evidence (cohort agreement, control-plane change event); operator lifts the cap | 11 | cohort evidence never occurred in dev runs; change events explain 0 of 78 usage shifts and 16% of configuration shifts | **not shown to help**; keep only as a fallback |
| 16 | *Fallback:* attribution against the trusted baseline with the baseline state recorded | 1 or 11 | 67.0% Top-1, 81.1% Top-3 | weak |
| 17 | *Fallback:* schema-free event encoder | 1 | level-shift AUC 1.00; spike AUC 0.68 | weak |
| 18 | *Fallback:* cohort seeding of new entities | 1 | 16 entities: 12 h vs 156 h | small sample |

## 5. Removed from the claims (kept out until they beat the current design on new data)

| Removed | Reason |
|---|---|
| Tri-signal fusion, uncertainty gate, episode novelty | Never built or evaluated. |
| Evidence-weighted promotion as part of an independent claim | Not shown to help; including it only narrows claim 11. Moved to dependent 15. |
| Bounded drift as a standalone lead claim | A long window or a frozen baseline gives a similar bound; Kloft and Laskov analyse bounded influence. |
| Explanation as an independent claim | Rule-based determinism is not new; accuracy is modest. |
| "Attacker cost bound" as the technical effect | The cap does not stop a 3σ attack at the tuned settings. |

## 6. Known weaknesses an examiner or the evaluation will expose

1. Every attack was written by the team. The validation checks were built against our own attack types. No third-party attack
   data could be obtained in this environment. This is the largest single weakness.
2. The dual trigger's false-alert rate is 10% (95% interval 2–21%) on NAB dev and 8% (2–13%) on CoreStack dev against 5%. The
   bound multiple m was tuned per dataset (9.92 and 6.3) and CoreStack thresholds did not transfer to fresh CoreStack (2 of 8
   clean entities false-alerted). No rule for setting m without per-dataset tuning exists yet.
3. Fresh CoreStack has only 8 clean entities from 6 resources: no detection or false-alert claim on it has power. Its value is
   the 41 real-shift series.
4. NAB entities are day-resampled replicas of 14 (dev) or 22 (fresh) real series with a synthetic order; intervals resample whole
   series, but 11–14 clusters is small.
5. Detection equals clipped CUSUM. Component results (`ABLATION.md`): each part covers a gap of another, but hold-only,
   shadow-only and unvalidated-bound variants were not each run on the frozen sets.
6. The stated bound on promotion is weak at the tuned settings (about 4σ per step) and covers promotion only (`GUARANTEE.md`).
7. Rollback keeps a stronger line on attack absorption on NAB (median 0.17 at +60 days) at the price of resolving fewer
   legitimate shifts (44%).
8. The prior-art search is a desk search; arXiv 2609.04388 could not be read.
9. Software and mathematical-method objections: the effect is integrity of stored state, with a stated bound and a recorded,
   reversible record, not a statistical result as such.

## 7. Status of the five further steps requested

| Step | Status |
|---|---|
| 1. Test on attacks the team did not write | **Not done.** No public attack data or CoreStack red-team was reachable from this environment. Plan item. |
| 2. Ablate each component against the full design | **Partly done** from existing runs (`ABLATION.md`): validated bound only, bound plus ledger, trigger only, trigger plus ledger, dual with and without ledger. Hold-only and shadow-only are not separate runs. |
| 3. Formal guarantee | **Done for promotion steps** (`GUARANTEE.md`), tested on dev data. Not an end-to-end bound; weak at tuned settings. |
| 4. False alerts at 5% on a larger fresh clean set; explain m | **Not done.** Needs new data. Fresh sets are already used. |
| 5. Formal prior-art search; read arXiv 2609.04388 | **Desk search extended** with a search log and differs-from rows (`PRIOR_ART.md`); the paper is still unreadable and a classification-based search is still needed. |
