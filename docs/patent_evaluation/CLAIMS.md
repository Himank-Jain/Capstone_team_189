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
A held baseline is not discarded: a shadow baseline learns during the hold and is promoted in capped steps, each recorded in a
ledger with a restore point. **The two parts share one number.** The validated displacement bound that decides when the hold begins
is also the unit in which the promotion allowance is expressed, and the ledger records which bound, from which source and after what
validation outcome each step was sized (claim 2). A failed validation therefore changes both the trigger and the allowance
(claim 3).

## 2. Technical problem and effect (the wording to defend)

* **Problem.** A baseline that always adapts can be rewritten by a slow adversary, or by a poisoned calibration period, before
  anyone is alerted. A baseline that never adapts leaves real change alerting for ever.
* **Effect 1 (claim 1): the stored baseline is protected from a poisoned start and from slow drift.** Fresh2 (311 clean series,
  148 resources), self-calibrated design: poisoned calibration caught in 85% (80-89), the same as the tuned dual trigger and against
  2% for the adaptive baseline; 2σ, 3σ and fast 4σ attacks detected in 85% (80-89) with 0% (0-1) false alerts, against 79% at 9%
  false alerts for the tuned dual trigger. **Plain detection is not the differentiator on fresh2: the unguarded adaptive baseline
  also flags 81%** (62% without Public IP, where the self-calibrated design has 69%), because most of these series have a tiny robust scale. What the guard
  adds is the stored state: poisoned calibration 85% against 2%, and the 3σ attack absorbed into the baseline in 0% against 15%.
  The 15% ceiling is 48 bucket series on which no strategy detects any injected attack (cause not diagnosed); on the other 263
  series detection is 100%. Without Public IP series: 69% (59-77) at 1% false alerts against 58% at 18%. Development data: 98% at 3% false alerts. Validation ablation (earlier run): 21 of 21 held-out NAB entities with
  validated bounds against 1 of 21 without; 39 of 39 against 28 of 39 on CoreStack.
* **Effect 2 (claim 2): the held baseline is not discarded, and every step is recorded.** The shadow baseline is promoted in
  capped steps with a ledger entry and a restore point per step (unit-tested, no field data). Absorbed attack at the end of the
  series: 0% (0-1) of 3σ attacks against 5% (2-8) for the tuned dual trigger and 15% for the adaptive baseline. **That figure does not
  come from promotion:** hold-only gives the same 0% on fresh2 because a promotion cannot complete within its 30-day horizon.
  The cap is shown to matter on development data (without it 78% of 3σ attacks and 85% of greedy attackers succeed, against 20% and 12%).
* **A stated bound on promotion.** Each step moves the baseline by at most an allowance, and steps are at least 14 days apart
  (`GUARANTEE.md`). With the self-calibrated unit at the 0.5σ floor (98% of fresh2 series) a step is about 0.5σ, so a 3σ shift takes
  at least 70 days; the largest rise in stored displacement in any 14-day window after the first alert was 0.50σ (median 0.45σ). It
  bounds promotion only. An end-to-end bound on displacement was tested and **does not hold** (`GUARANTEE.md`).
* **Greedy attacker (Kloft and Laskov strategy, implemented by us).** Held in 100% of cases, stored displacement 0.4σ at the end,
  reached its 6σ goal in 0 of 49 on fresh2 (adaptive baseline: 49 of 49) **within that set's 30-day horizon**. Development data had shown a leak (56%) through a hold that
  withholds only the breaching reading; freezing at the first breach reduced it to 12% there and 0% on fresh2. **Over a long horizon the promotion path lets this attacker through:**
  65% reach the goal on day-resampled CoreStack (140 days after the event) and 99% on NAB (130 days), against 0% and 3% for hold-only (`ABLATION.md`, long-horizon results).
* **Cost, stated in the same breath.** Legitimate growth that is flagged stays unresolved after 30 days in 99% of cases (tuned
  dual trigger: 13%), because steps are about 0.5σ per 14 days; real shifts 73% unresolved against 67% (intervals overlap). A 1σ
  stealth attack is detected in 14% (tuned: 78%) and a business-hours 4σ attacker in 1% (tuned: 79%).
* **Not claimed.** That attacks are never absorbed: a persistent attacker level that stays within the allowance over a long time
  still moves the baseline, only slowly. This is now measured on two long-horizon sets: a 3σ attack is absorbed in 98-100% of series by 100 days after the
  event at the default allowance (delayed by 1 day on NAB and 7 days on CoreStack against adopting in full; hold-only: 48% and 8%). Detection better than a CUSUM comparator at equal false alerts on every attack type: it is
  better at 2σ to 4σ and worse at 1σ and for business-hours attacks. Rollback absorbs less of an attack than the proposal and
  resolves less growth: a different point, not above it.

## 2a. The link between claims 1 and 2 (claim 3): what is argued and what the evidence supports

**The link.** The bound `b` that claim 1 derives from the entity's validated calibration decides when the hold begins. Claim 2's allowance is
`k · b` (`k` = allowance multiple, default 1), so the validated number is also the unit in which the held baseline is released. A failed
validation changes both: the hold trigger and the allowance fall back to the same default bound. Every ledger entry records `allowance`,
`unit` (= `b`), `unit_source` (`validated_bound`, `fallback_bound`, `unvalidated_bound`, `external_unit` or `fixed`), `bound_source`,
`validation` outcome, `allow_multiple`, `need`, `step` and `capped`, so each step is tied to the bound and to the validation that approved
it (`phase0/guard/drift_guard.py`; 7 new unit tests; the behaviour of every earlier design is unchanged).

**What was tested, with the tests fixed before the results were read** (`ABLATION.md`). Variants: hold-only (claim 1 alone), shadow-only
(claim 2 alone, with a CUSUM trigger because it has no bound), both with the allowance fixed in σ, both with the bound unvalidated, both without the
cap, and the design.

| Question | CoreStack dev (65 clean entities) | fresh2 (311 clean series) | Reading |
|---|---|---|---|
| Does the design beat the sum of its parts? (interaction `full - H - S + adaptive`, points) | C1 -55 [-68, -44]; C2 +4 [-13, +21]; C3 -63 [-84, -41] | C1 -1 [-3, +1]; C2 -1 [-2, +1]; C3 -10 [-23, 0] | **No.** Not on any pre-declared column |
| Does it beat the better single part? (`full - max(H, S)`) | C1 -11; **C2 +18 [4, 32]**; C3 -12 | C1 0; C2 **-53 [-60, -45]**; C3 -2 | only on dev C2; reversed on fresh2 |
| Does the cap matter? (full minus no-cap) | C1 +58, C2 +35, C3 +68 | C1 0, C2 0, C3 +10 [0, 26] | essential on dev; invisible on fresh2 (a promotion cannot complete in 30 days) |
| Does linking the allowance to the bound help? (`L1 - F0.5`, step size matched) | C1 -1.5 [-4.8, 0]; C2 0 | 0 (98% of bounds are the floor) | **not shown** |
| Does validating the bound help the self-calibrated design? (full minus unvalidated) | C1 +2 [0, 5]; C2 +2 [0, 6]; C3 0 | 0 | **hardly**; it mattered for the tuned design (39 of 39 against 28 of 39) |
| Does freezing at the first breach help? (full minus partial hold) | C3 +41 [26, 58] | 0 | greedy attacker only |

**How to argue claim 3.** On the evidence, not as an unexpected synergy: there is none to show. Argue it as a *structural and functional*
link: one validated number is both the trigger and the release unit, so, with the stable shadow as the only evidence (`k` = 1), one release step is never larger than the displacement that was allowed to trigger the
hold, and a failed validation degrades both safely and visibly (the ledger says so). The measured value of the link over a fixed allowance of the same size is zero on both sets, so claim 3 stays
a fallback that preserves the combination if claims 1 and 2 are split, not a lead claim.

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

### Independent claim 2: shadow, capped promotion and ledger, allowance derived from a validated bound

> 2. A computer-implemented method for a monitoring system that holds a live baseline of a monitored entity against updates,
> comprising:
> (a) storing incoming readings during the hold in a shadow baseline;
> (b) obtaining a displacement bound for the entity that was derived from calibration readings of the entity and validated before
> use, a default bound being used instead when the validation fails;
> (c) promoting the shadow baseline into the live baseline only after the shadow baseline has met a stability criterion for a
> minimum period, a displacement applied by one promotion being limited to an allowance that is a multiple of the displacement
> bound; and
> (d) storing for each promotion a ledger record that includes the allowance, the displacement bound from which the allowance was
> derived and the outcome of the validation, and a restore point of the live baseline taken before the promotion, so that the
> promotion can be reverted and the readings it affected re-scored.

Claim 2 does not depend on claim 1: it needs a held baseline, not the trigger that caused the hold (a sequential detector or an
operator also qualifies), and it carries its own recital of a validated bound.

### Claim 3: the combination (the functional link)

> 3. A computer-implemented method comprising the steps of claim 1 and, while the live baseline is in the hold state, the steps (a),
> (c) and (d) of claim 2, wherein the displacement bound of step (b) of claim 1 is the displacement bound from which the allowance
> of step (c) of claim 2 is derived, such that a single validated calibration sets both the displacement at which the hold begins
> and the size of each step by which the held baseline is later released, and a failed validation replaces both with the same
> default bound.

Claim 3 is the fallback if claims 1 and 2 are split by restriction or found separately obvious: it claims the interaction, i.e.
the use of one validated number as trigger and as release unit, and the ledger record that ties each step to that number and to the
validation that approved it. Its argument and evidence are in section 2a.

Add a system claim and a computer-readable-medium claim for each, in the same words. Word the claims around stored system state
and operations (store, validate, hold, shadow, promote, record, restore) and the measured integrity effect.

## 4. Dependent claims and evidence status

Dependent features carry the prefix D so they cannot be confused with the three lead claims (earlier drafts numbered them 2 to 5 and 12 to 18).

| # | Dependent feature | Depends on | Evidence | Status |
|---|---|---|---|---|
| D1 | **Self-calibrated bound:** the bound is a quantile (1 - α/4) of the largest displacement from the trusted snapshot observed in a plurality of clean continuations of the calibration readings, each later day replaced by a calibration day of the same day type drawn with replacement, never below a fixed floor; default bound = median such bound of the deployment's own entities | 1 | `SELFCAL.md`: 3% (0-7) false alerts on dev, 0% (0-1) on fresh2, no number tuned on any dataset | supported; **the bound is the fixed floor for 98% of fresh2 series (62% on dev)**, so the resampling is shown to be sufficient, not shown to beat a fixed 0.5σ bound |
| D1b | *Fallback:* bound = multiple of the entity's own 99th-percentile calibration drift, multiple tuned on separate series | 1 | tuned design: m = 9.92 NAB, 6.3 CoreStack; 0% detection of 1-4σ attacks on fresh2 (floor tuned to 4σ) | weak: m and floor differ by dataset and the tuned bound did not trip on fresh2 |
| D2 | Alert-period exclusion and split-half trend test on the calibration readings | 1 | validation ablation 21/21 vs 1/21 | supported |
| D2b | *Tuned form only:* cohort p95 cross-check and cap at 1.5 times the cohort median bound | 1 (with D1b) | validation ablation; **with the self-calibrated bound it raised false alerts to 15% on dev** | do not combine with D1 |
| D3 | Per-bucket bound floor; weekday and weekend coherent shift statistic | 1 | regression tests | supported |
| D4 | **Freeze on hold:** at the first breach the entity is frozen and every later reading goes to the shadow baseline | 1 | greedy attacker reached its goal in 56% (partial hold) → 12% (freeze) on dev, 0 of 49 on fresh2; no change in false alerts | supported (attack written from a paper by us) |
| D5 | *Optional:* second trigger, a sequential detector on the residual against the snapshot, also causes the hold; residual clipped | 1 | tuned dual trigger: detects 1σ and business-hours attacks (78%, 79% on fresh2) at **9% (4-14) false alerts, 18% (9-27) without Public IP**; a self-calibrated threshold gave 14% on dev | optional: threshold not portable by the self-calibration; does not meet the 5% target outside dev |
| D6 | Revert of a promotion and re-score of the readings it made normal | 2 | unit tests | implemented, no field data |
| D7 | Promotion steps at least the shadow period apart; step size at most a stated allowance | 2 | `guarantee_check`: 715 steps, 0 violations; self-calibrated design `envelope_check`: 186 steps, 0 over the allowance | supported |
| D8 | Episode continuity after a capped step | 2 | unit tests | implemented |
| D9 | *Optional:* allowance increased by evidence (cohort agreement, control-plane change event); operator lifts the cap | 2 | cohort evidence never occurred in dev runs; change events explain 0 of 78 usage shifts and 16% of configuration shifts | **not shown to help**; keep only as a fallback |
| D10 | **Deterministic explanation** (attribute, evidence, ordered rules, confidence, versioned knowledge base), with attribution run against the trusted baseline and the baseline state recorded | 1 or 2 | Reproducible: 13,500 builds over 54 cases, one output each, no network (`determinism_check.json`). Cause category (synthetic generator, constant baseline): 67.0% top-1, 81.1% top-3, 810 runs. **Real telemetry, metric attribution against the snapshot** (`UNIFIED_RESULTS.md` B1): top-1 42-94%, top-3 (>= 5 metrics) 85-100%; beats the adaptive reference only 39+ days after the event (+43 to +57 points), equal at 29 days (fresh2), worse early; 0.4-0.8 false attributions per control case | **partly supported**: the determinism is a measured property; the accuracy is modest and the link to the snapshot has value only after absorption |
| D11 | *Fallback:* schema-free event encoder | 1 | synthetic level-shift AUC 1.00 with online statistics; **real telemetry: AUC 0.56-0.66 in vocabulary and 0.50 on unseen schemas against 0.83-1.00 for a per-metric z-score** (`UNIFIED_RESULTS.md` C) | **not supported on real data**; do not claim |
| D12 | **Cohort seeding** of new entities from other resources of the same entity type and metric | 1 | dev 87 entities: scoring starts at 12 h vs 156 h, detected 61% vs 40% (+21 [9, 33]); fresh2 314 entities / 151 resources: detected 34% vs 5% (+29 [23, 35]); false alerts unchanged (`UNIFIED_RESULTS.md` D) | **supported on two sets**, same cloud only |
| D13 | Incident collapsing during a hold, severity capped | 1 | median 1 incident per run against 6-15 flag-days; 6-38% of flag-days attach to an open incident (`UNIFIED_RESULTS.md` E) | small effect |

## 5. Removed from the claims (kept out until they beat the current design on new data)

| Removed | Reason |
|---|---|
| Tri-signal fusion, uncertainty gate, episode novelty | Never built or evaluated. |
| Evidence-weighted promotion as part of an independent claim | Not shown to help; including it only narrows claim 2. Moved to dependent D9. |
| Bounded drift as a standalone lead claim | A long window or a frozen baseline gives a similar bound; Kloft and Laskov analyse bounded influence. |
| Explanation as an independent claim | Rule-based determinism is not new; accuracy is modest (cause category 67.0% top-1 on the synthetic generator; metric top-1 42-94% on real telemetry). Kept as dependent D10. |
| Schema-free event encoder as a claim ("Invention C") | Real-data test negative (D11). |
| "Attacker cost bound" as the technical effect | The cap does not stop a 3σ attack at the tuned settings. |

## 6. Known weaknesses an examiner or the evaluation will expose

1. **No third-party attack data.** Every attack is ours or a strategy from a paper that we implemented (Rubinstein et al. IMC 2009
   boiling frog; Kloft and Laskov JMLR 2012 greedy attacker). A desk search found no public dataset of baseline poisoning. The
   validation checks were built against our own attack types. The boiling-frog evidence is thin (45 series from 19 resources at
   g = 1.15, none at 1.01 and 1.02, where the self-calibrated design detects 11% against 71% for the tuned dual trigger). The only third-party
   data that could be fetched (`THIRD_PARTY.md`) are labelled server incidents, not poisoning: the guarded baseline detects them about as often as
   the unguarded one (46% against 42%, 8 machines) and 31% of series end the run held.
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
   design cannot hold its false-alert rate. Component results (`ABLATION.md`, dev and fresh2): **no super-additivity on any pre-declared
   column**, and on fresh2 the design is indistinguishable from hold-only on every column.
7. The stated bound covers promotion only. An end-to-end displacement envelope (k+1 bounds plus the steps) was tested on dev and is
   exceeded in 25 of 65 greedy runs, 17 of 65 fast-attack runs and 9 of 65 benign-growth runs (`GUARANTEE.md`); the cause is not
   established.
8. Rollback keeps a stronger line on attack absorption on NAB (median 0.17 at +60 days) at the price of resolving fewer
   legitimate shifts (44%).
9. The prior-art search is a desk search. arXiv 2609.04388 has now been read (through ar5iv and the arXiv HTML; the PDF returned an
   empty body): it concerns classifier promotion gates after drift alarms, treats poisoning as out of scope and has no shadow
   baseline, cap or restore point (`PRIOR_ART.md` section 6). Its reference list was not checked and a formal classification-based
   search is still needed.
10. **Claim 2 adds nothing measurable on fresh2, and claim 3's link adds nothing over a fixed allowance of the same size on either set.** On dev the
    design beats the better single part on one column (+18 points) and the cap is essential; on fresh2 the design equals hold-only and sits 53 points
    below claim-2-alone on operability. Validation of the calibration adds about 0 for the self-calibrated bound (+2 [0, 5] on dev). The horizon
    (30 to 40 days after the event, one promotion at most) limits what these sets can show about promotion; the long-horizon sets (NAB, synthetic order and dependent
    entities; CoreStack with day-resampled days after day 60) show the dial moving, and see item 12.
11. **At the proposed allowance a fast 4σ attack is still absorbed** (1.5σ or more stored at the end) for 42% to 52% of dev entities (hold only: 11%); the
    allowance does not protect against fast large attacks beyond what the hold does.
12. **Over a long horizon the capped promotion path admits a sustained attacker.** Long-horizon sweeps (`ABLATION.md`; synthetic or day-resampled order, exploratory): at the default allowance a 3σ stealth attack is
    absorbed in 14% (NAB) and 7% (CoreStack) of series 30 days after the event, and in 98% and 100% at 100 days; a greedy attacker reaches its goal in 99% and 65%, against 3% and 0% for hold-only; the
    pre-declared range rule (at most 5% absorbed and at least 50% of flagged growth resolved) is met by no setting at any horizon. A persistent legitimate shift and a persistent attack at the same level are the same input to a
    stability-gated promotion, so the allowance sets the **speed** (and the time to notice and revert from the ledger), not the outcome. The security value of claim 2 over a long horizon is time and an audit trail, not
    exclusion; the hold of claim 1 is what keeps an attacker out until a promotion occurs. A possible remedy, **not tested**: a cumulative ceiling on displacement from the trusted snapshot beyond which promotion needs
    operator approval (operator approval lifting the cap is already a dependent claim).
13. Software and mathematical-method objections: the effect is integrity of stored state, with a stated bound on promotion and a
    recorded, reversible record, not a statistical result as such.

## 6a. Unified scope (adopted 15 October 2026)

The team adopted the structure of the 25-slide unified proposal (drift guard, deterministic explanation, schema-free events, cohort seeding) as the
project scope. `UNIFIED_GAP.md` compares every statement of that file with code and measurement; `UNIFIED_RESULTS.md` holds the new measurements.
Outcome: the guard claims (1 to 3) stay as above with the same limits; explanation is dependent D10 (partly supported); schema-free events are
not supported on real data (D11); cohort seeding is supported on two sets (D12); collapsing is a small effect (D13). The file's planned figures
(93.6%, 94.0%, 88.1%, 91.4%, 2,140 entities) are not results of this repository.

## 7. Status of the five further steps requested

| Step | Status |
|---|---|
| 1. Test on attacks the team did not write | **Partly done.** Permission to download was given. No public dataset of baseline poisoning exists or is reachable (Kaggle, Mendeley, Zenodo and similar hosts are blocked by the session's network policy). Third-party **incident** data (SMD, 8 machines, 128 MB) was run: no gain and no loss in detection, 31% of series held at the end (`THIRD_PARTY.md`). Two attacks from the literature were implemented by us (`lit_attacks.py`). |
| 2. Ablate each component against the full design, including the interaction | **Done on dev and fresh2** (`ABLATION.md`): hold-only, shadow-only, unvalidated, unlinked and no-cap variants and a pre-declared interaction test. **The combination is not super-additive on any column**; the design equals hold-only on fresh2. |
| 2b. Make the claims interact (claim 2 allowance from the validated bound, ledger records validation; claim 3 combination) | **Done in the claims and code** (section 2a, 3; ledger fields; unit tests). The measured value of the link over a fixed allowance is 0. |
| 2c. Promotion trade-off as a curve; name an operating range | **Done, with a negative result.** Dev curve (`allowance_curve_ev0_cs_dev.png`): range 0.5 to 1 validated bounds proposed post hoc (the pre-declared rule is met by no setting). **fresh2: flat** (30-day horizon, no step completes), so the range is not confirmed on fresh data. **Long horizons (NAB, day-resampled CoreStack; exploratory): the allowance sets the speed at which a sustained attack is adopted, not whether; no setting satisfies the rule at any horizon** (`ABLATION.md`, item 12 above). |
| 3. Formal guarantee | **Done for promotion steps** (`GUARANTEE.md`), including the self-calibrated design. An end-to-end bound was tested and fails; not claimed. |
| 4. False alerts at 5% on a larger fresh clean set; explain m | **Done with caveats.** A label-free bound replaces the tuned `m`; fresh2 has 311 clean series from 148 resources and 0% (0-1) false alerts, but the bound is the fixed floor for 98% of them and legitimate growth pays for it. |
| 5. Formal prior-art search; read arXiv 2609.04388 | **Paper read** (`PRIOR_ART.md` section 6). Desk search with a search log and differs-from rows; a classification-based search by a professional is still needed. |
