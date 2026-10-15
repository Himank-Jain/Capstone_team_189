# Candidate claims, technical effect and evidence status (revised 15 October 2026, after the second fresh run)

Working draft for the patent attorney. Not legal advice. Two designs are described. The **tuned design** (frozen at commit
`9c892e5`, numbers in `FINAL_TABLES.md`) sets its bound as a multiple of the entity's own calibration drift with the multiple and
a floor tuned per dataset. The **self-calibrated design** (`SELFCAL.md`, frozen at `2af0fca`) derives the bound from the entity's
own calibration days with no number tuned on any dataset; it is the design now proposed for claim 1. "dev" = development data,
"fresh2" = 336 series from 158 resources never run before the freeze (pre-registered in `PREREG_FRESH2.md`), run once. Component
results are in `ABLATION.md`, the bound on promotion in `GUARANTEE.md`, prior art in `PRIOR_ART.md`.

## 1. What the invention is

A monitoring system that keeps, for each monitored entity, a trusted baseline snapshot and a live adaptive baseline, derives a
displacement bound from a **validated** calibration period, and **holds** the live baseline when the bound is exceeded.
Separately, a held baseline is not discarded: a shadow baseline learns during the hold and is promoted in capped steps, each
recorded in a ledger with a restore point.

## 2. Technical problem and effect (the wording to defend)

* **Problem.** A baseline that always adapts can be rewritten by a slow adversary, or by a poisoned calibration period, before
  anyone is alerted. A baseline that never adapts leaves real change alerting for ever.
* **Effect 1 (claim 1): the stored baseline is protected from a poisoned start and from slow drift.** Fresh2 (311 clean series,
  148 resources), self-calibrated design: poisoned calibration caught in 85% (80-89), the same as the tuned dual trigger and against
  2% for the adaptive baseline; 2σ, 3σ and fast 4σ attacks detected in 85% (80-89) with 0% (0-1) false alerts, against 79% at 9%
  false alerts for the tuned dual trigger. **Plain detection is not the differentiator on fresh2: the unguarded adaptive baseline
  also flags 81%** (62% without Public IP, against 69% here), because most of these series have a tiny robust scale. What the guard
  adds is the stored state: poisoned calibration 85% against 2%, and the 3σ attack absorbed into the baseline in 0% against 15%.
  The 15% ceiling is 48 bucket series on which no strategy detects any injected attack (cause not diagnosed); on the other 263
  series detection is 100%. Without Public IP series: 69% (59-77) at 1% false alerts against 58% at 18%. Development data: 98% at 3% false alerts. Validation ablation (earlier run): 21 of 21 held-out NAB entities with
  validated bounds against 1 of 21 without; 39 of 39 against 28 of 39 on CoreStack.
* **Effect 2 (claim 2): the held baseline is not discarded, and every step is recorded.** The shadow baseline is promoted in
  capped steps with a ledger entry and a restore point per step (unit-tested, no field data). Absorbed attack at the end of the
  series: 0% (0-1) of 3σ attacks against 5% (2-8) for the tuned dual trigger and 15% for the adaptive baseline.
* **A stated bound on promotion.** Each step moves the baseline by at most an allowance, and steps are at least 14 days apart
  (`GUARANTEE.md`). With the self-calibrated unit at the 0.5σ floor (98% of fresh2 series) a step is about 0.5σ, so a 3σ shift takes
  at least 70 days; the largest rise in stored displacement in any 14-day window after the first alert was 0.50σ (median 0.45σ). It
  bounds promotion only. An end-to-end bound on displacement was tested and **does not hold** (`GUARANTEE.md`).
* **Greedy attacker (Kloft and Laskov strategy, implemented by us).** Held in 100% of cases, stored displacement 0.4σ at the end,
  reached its 6σ goal in 0 of 49 on fresh2 (adaptive baseline: 49 of 49). Development data had shown a leak (56%) through a hold that
  withholds only the breaching reading; freezing at the first breach reduced it to 12% there and 0% on fresh2.
* **Cost, stated in the same breath.** Legitimate growth that is flagged stays unresolved after 30 days in 99% of cases (tuned
  dual trigger: 13%), because steps are about 0.5σ per 14 days; real shifts 73% unresolved against 67% (intervals overlap). A 1σ
  stealth attack is detected in 14% (tuned: 78%) and a business-hours 4σ attacker in 1% (tuned: 79%).
* **Not claimed.** That attacks are never absorbed: a persistent attacker level that stays within the allowance over a long time
  still moves the baseline, only slowly. Detection better than a CUSUM comparator at equal false alerts on every attack type: it is
  better at 2σ to 4σ and worse at 1σ and for business-hours attacks. Rollback absorbs less of an attack than the proposal and
  resolves less growth: a different point, not above it.

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
| 2 | **Self-calibrated bound:** the bound is a quantile (1 - α/4) of the largest displacement from the trusted snapshot observed in a plurality of clean continuations of the calibration readings, each later day replaced by a calibration day of the same day type drawn with replacement, never below a fixed floor; default bound = median such bound of the deployment's own entities | 1 | `SELFCAL.md`: 3% (0-7) false alerts on dev, 0% (0-1) on fresh2, no number tuned on any dataset | supported; **the bound is the fixed floor for 98% of fresh2 series (62% on dev)**, so the resampling is shown to be sufficient, not shown to beat a fixed 0.5σ bound |
| 2b | *Fallback:* bound = multiple of the entity's own 99th-percentile calibration drift, multiple tuned on separate series | 1 | tuned design: m = 9.92 NAB, 6.3 CoreStack; 0% detection of 1-4σ attacks on fresh2 (floor tuned to 4σ) | weak: m and floor differ by dataset and the tuned bound did not trip on fresh2 |
| 3 | Alert-period exclusion and split-half trend test on the calibration readings | 1 | validation ablation 21/21 vs 1/21 | supported |
| 3b | *Tuned form only:* cohort p95 cross-check and cap at 1.5 times the cohort median bound | 1 (with 2b) | validation ablation; **with the self-calibrated bound it raised false alerts to 15% on dev** | do not combine with 2 |
| 4 | Per-bucket bound floor; weekday and weekend coherent shift statistic | 1 | regression tests | supported |
| 4b | **Freeze on hold:** at the first breach the entity is frozen and every later reading goes to the shadow baseline | 1 | greedy attacker reached its goal in 56% (partial hold) → 12% (freeze) on dev, 0 of 49 on fresh2; no change in false alerts | supported (attack written from a paper by us) |
| 5 | *Optional:* second trigger, a sequential detector on the residual against the snapshot, also causes the hold; residual clipped | 1 | tuned dual trigger: detects 1σ and business-hours attacks (78%, 79% on fresh2) at **9% (4-14) false alerts, 18% (9-27) without Public IP**; a self-calibrated threshold gave 14% on dev | optional: threshold not portable by the self-calibration; does not meet the 5% target outside dev |
| 12 | Revert of a promotion and re-score of the readings it made normal | 11 | unit tests | implemented, no field data |
| 13 | Promotion steps at least the shadow period apart; step size at most a stated allowance | 11 | `guarantee_check`: 715 steps, 0 violations; self-calibrated design `envelope_check`: 186 steps, 0 over the allowance | supported |
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

1. **No third-party attack data.** Every attack is ours or a strategy from a paper that we implemented (Rubinstein et al. IMC 2009
   boiling frog; Kloft and Laskov JMLR 2012 greedy attacker). A desk search found no public dataset of baseline poisoning. The
   validation checks were built against our own attack types. The boiling-frog evidence is thin (45 series from 19 resources at
   g = 1.15, none at 1.01 and 1.02, where the self-calibrated design detects 11% against 71% for the tuned dual trigger).
2. **The self-calibrated bound is the fixed floor for 98% of fresh2 series** (62% on dev). Its low false-alert rate there comes
   from the fixed 0.5σ constant of the original design, not from the resampling. The sequential trigger's threshold is still tuned
   and exceeded the 5% target on fresh2 (9%, 18% without Public IP). The old tuned `m` (9.92, 6.3) is demoted to a fallback.
3. **Fresh set size is now 311 clean series from 148 resources**, but 157 are Public IP series, 48 are bucket series on which no
   strategy detects any injected attack, and the resources come from the same customer dump as the development set. NAB was not
   rerun with the self-calibrated design in the main evaluation (see `SELFCAL.md` for any later run).
4. **Legitimate growth is not resolved within the horizon** (99% unresolved after 30 days) because the stated step bound is about
   0.5σ per 14 days; the trade-off is set by the allowance multiple, which was not tuned.
5. **Small and business-hours attacks are not caught** by the self-calibrated design: 14% at 1σ, 1% for a 4σ attack in business hours.
6. Detection equals a CUSUM comparator at 2σ to 4σ at the tuned design's false-alert rate, and is better only because the tuned
   design cannot hold its false-alert rate. Component results (`ABLATION.md`): hold-only, shadow-only and unvalidated-bound
   variants were not each run on the fresh sets.
7. The stated bound covers promotion only. An end-to-end displacement envelope (k+1 bounds plus the steps) was tested on dev and is
   exceeded in 25 of 65 greedy runs, 17 of 65 fast-attack runs and 9 of 65 benign-growth runs (`GUARANTEE.md`); the cause is not
   established.
8. Rollback keeps a stronger line on attack absorption on NAB (median 0.17 at +60 days) at the price of resolving fewer
   legitimate shifts (44%).
9. The prior-art search is a desk search. arXiv 2609.04388 has now been read (through ar5iv and the arXiv HTML; the PDF returned an
   empty body): it concerns classifier promotion gates after drift alarms, treats poisoning as out of scope and has no shadow
   baseline, cap or restore point (`PRIOR_ART.md` section 6). Its reference list was not checked and a formal classification-based
   search is still needed.
10. Software and mathematical-method objections: the effect is integrity of stored state, with a stated bound on promotion and a
    recorded, reversible record, not a statistical result as such.

## 7. Status of the five further steps requested

| Step | Status |
|---|---|
| 1. Test on attacks the team did not write | **Not done.** No public dataset of baseline poisoning was found, and downloading unvetted data needs the owner's permission. Two attacks from the literature were implemented and run (`lit_attacks.py`); this is weaker than third-party data. |
| 2. Ablate each component against the full design | **Partly done** (`ABLATION.md`; the freeze-on-hold and self-calibrated variants are in `SELFCAL.md`). Hold-only and shadow-only are not separate runs. |
| 3. Formal guarantee | **Done for promotion steps** (`GUARANTEE.md`), including the self-calibrated design. An end-to-end bound was tested and fails; not claimed. |
| 4. False alerts at 5% on a larger fresh clean set; explain m | **Done with caveats.** A label-free bound replaces the tuned `m`; fresh2 has 311 clean series from 148 resources and 0% (0-1) false alerts, but the bound is the fixed floor for 98% of them and legitimate growth pays for it. |
| 5. Formal prior-art search; read arXiv 2609.04388 | **Paper read** (`PRIOR_ART.md` section 6). Desk search with a search log and differs-from rows; a classification-based search by a professional is still needed. |
