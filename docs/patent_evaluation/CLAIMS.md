# Candidate claims, technical effect and evidence status

Working draft for the patent attorney. Not legal advice. Numbers are from `FINAL_TABLES.md` (frozen design, 5% target false-alert
rate; "dev" = development data, "fresh" = series and resources never run before the design was frozen at commit `9c892e5`).

## 1. What the invention is, in one paragraph

A monitoring system that keeps, for each monitored entity, a **trusted baseline snapshot**, a **live adaptive baseline** and a
**shadow baseline**, and that governs when the live baseline may change. A *validated* calibration period fixes the reference
and bounds of two triggers (a per-entity displacement bound and an outlier-clipped sequential detector on the residual against
the snapshot). Either trigger switches the entity from UPDATE to HOLD: readings stop entering the live baseline and enter the
shadow baseline. The shadow baseline is promoted only after it has been stable for a minimum period, in steps whose size is
limited by an allowance built from independent evidence, and every step is written to a persisted ledger with a restore point so
that it can be reverted and the readings it affected re-scored.

## 2. Technical problem and effect (the wording to defend)

* **Problem.** A baseline that always adapts can be rewritten by a slow adversary, or by a poisoned calibration period, before
  anyone is alerted. A baseline that never adapts (or only raises alarms) never follows legitimate change, so alerts persist.
* **Effect, measured:** the stored baseline state of a monitoring system is protected *and* kept usable.
  1. *Detection at the level of the best sequential detector, at a matched false-alert rate* (not better than it).
     Fresh NAB: 2σ stealth attacks detected 100% (95% interval 100–100%), clipped CUSUM 100%, adaptive 46%, rollback 50%.
  2. *Poisoned calibration is caught* because the displacement bound is validated before use. Fresh NAB 100% (adaptive 35%);
     CoreStack dev 98% (95–100) against 66% for the clipped CUSUM and 2% for the adaptive baseline. Validation ablation (earlier
     run): 21 of 21 held-out NAB entities with validated bounds against 1 of 21 without; 39 of 39 against 28 of 39 on CoreStack.
  3. *Legitimate sustained shifts resolve* instead of alerting indefinitely. Share of flagged legitimate growth still unresolved at
     the end: NAB dev 6%, NAB fresh 0%, CoreStack dev 25%; clipped CUSUM 84%, 83%, 69%; frozen 80%, 88%, 61%. Real shifts in
     fresh CoreStack data (41 series, 16 resources): unresolved 58% against 93% (CUSUM), 100% (frozen, rollback).
  4. *A bounded response window.* Median share of a 3σ stealth attack already in the stored baseline N days after the first alert
     (NAB dev): +14 d 0.18 (adaptive 0.44, clipped CUSUM 0.32), +30 d 0.56 (0.76, 0.59). CoreStack dev at +30 d: 0.00 (adaptive 0.57,
     clipped CUSUM 0.88). The window is a delay, not a prevention.
  5. *Every promotion step is revertible and re-scorable* (implemented and unit-tested; no field data).
* **What is NOT claimed:** that attacks are never absorbed. Persistent attacker levels are indistinguishable from persistent
  legitimate growth by statistics alone; by +60 days after the first alert the median share absorbed is 1.0 on NAB (dev and fresh).
  The ledger turns that into a delayed, recorded, reversible adoption.

## 3. Draft independent claim (system operations first, statistics in the dependents)

> 1. A computer-implemented method of maintaining a behavioural baseline for a monitored entity in a monitoring system, comprising:
> (a) storing for the entity a trusted baseline snapshot and a live baseline that is updated from incoming readings;
> (b) deriving, from readings of a calibration period, a displacement bound for the entity, and validating the calibration period
> before the bound is used by at least one of excluding readings in an alert period, testing the calibration readings for a trend,
> and comparing the entity's calibration statistics with those of a cohort of entities, wherein, when the validation fails, a
> default bound is used instead of a bound derived from the calibration readings;
> (c) determining for incoming readings a residual against the trusted baseline snapshot and, when either a sequential detector
> applied to the residual or the displacement of the live baseline from the snapshot exceeds the displacement bound, changing
> the entity from an update state to a hold state in which incoming readings are no longer applied to the live baseline and are
> stored in a shadow baseline;
> (d) promoting the shadow baseline into the live baseline only after the shadow baseline has met a stability criterion for a
> minimum period, the displacement applied by one promotion being limited to an allowance computed from a base allowance plus an
> additional allowance for each independent item of evidence associated with the entity; and
> (e) storing for each promotion a ledger record identifying the entity, the evidence used, the allowance and the displacement
> applied, together with a restore point of the live baseline taken before the promotion, so that the promotion can be reverted.

Notes for drafting: avoid "holding updates when drift is detected" as the point of novelty; (b)'s validated bound with default
fallback, (d)'s evidence-built allowance and (e)'s restore point are the specific mechanisms. Add a system claim and a computer-readable
medium claim in the same words.

## 4. Dependent claims and their evidence status

| # | Dependent feature | Evidence in this repository | Status |
|---|---|---|---|
| 2 | Re-scoring readings against the restore point to show what a promotion made normal | unit tests (`test_drift_guard_ledger.py`) | implemented, no field data |
| 3 | Revert of a promotion step records the revert in the ledger | unit test | implemented, no field data |
| 4 | Both triggers present; each given half the false-alert budget at calibration | dual vs single trigger, tables | supported on dev; on CoreStack the bound half could not reach its half budget (false-alert floor about 8%) |
| 4a | When calibration validation fails, the sequential detector's reference is anchored to the snapshot (residual 0, spread from first differences) | CoreStack dev poisoned detection 66% (clipped CUSUM) to 68% | negligible effect; keep only if the attorney sees value |
| 5 | Clipping of the standardised daily residual before the sequential detector | clipped vs plain CUSUM: threshold for 5% false alerts falls from 50 to 18 on CoreStack dev | supported (dev) |
| 6 | Evidence items: cohort agreement, control-plane change event, operator approval; operator alone lifts the cap | unit tests; evidence rates from CoreStack (change events explain 0 of 78 usage shifts; 16% of configuration shifts) | change-event evidence is sparse; cohort evidence had no signal on real data; keep as an allowance mechanism only |
| 7 | Episode continuity after a capped step (later hold within a gap is not a new incident) | `test_drift_guard_ledger.py`; incident counts | implemented |
| 8 | Weekday/weekend group-wise coherent shift statistic | regression test; a single median across buckets let half the buckets absorb an attack | supported |
| 9 | Per-bucket bound floor | real flat series produced zero bounds; floor test | supported |
| 10 | Attribution of a deviation against the trusted baseline state, with the baseline state recorded in the explanation | held-out run: 67.0% Top-1, 81.1% Top-3 over 810 runs | partly supported; accuracy modest, not improved in this round |
| 11 | Schema-free event encoder | level-shift AUC 1.00; spike AUC 0.68 against 0.76 for a simple feature | weak on spikes; keep only as a dependent claim |

## 5. Removed from the claims (and why)

| Removed | Reason |
|---|---|
| Bounded drift as a standalone or lead claim | A long window or a frozen baseline gives the same bound; CUSUM detects as well at matched false alerts; Kloft & Laskov (JMLR 2012) analyse bounded attacker gain. |
| Explanation as an independent claim | Rule-based determinism is not new; accuracy is modest; kept only as dependent claim 10. |
| Tri-signal fusion, episode novelty, uncertainty gate | Never built or evaluated. Moved to future work. |
| Cohort agreement as a promotion gate | No signal on real CoreStack data; coordinated attacks defeat it. Kept only as one allowance term. |
| Control-plane corroboration as a gate | Explains 0 of 78 usage-metric shifts; kept only as one allowance term. |
| "Attacker cost bound" as the technical effect | The cap is not binding after the first alert; replaced by the response-window effect in section 2. |

## 6. Known weaknesses an examiner or the evaluation will expose

1. The dual trigger's false-alert rate is 10% (95% interval 2–21%) on NAB dev and 8% (2–13%) on CoreStack dev against the 5%
   target; thresholds tuned on CoreStack dev did not transfer to CoreStack fresh (2 of 8 clean entities false-alerted for the
   CUSUM-type triggers).
2. Fresh CoreStack has only 8 clean entities from 6 resources: detection claims on it have no statistical power. Its value is the
   41 series with real shifts.
3. NAB entities are day-resampled replicas of 14 (dev) or 22 (fresh) real series; the order of days is synthetic. Intervals use
   a source-clustered bootstrap but 11–14 clusters is still small.
4. All attacks are team-generated additive shifts. No third-party attack data was available. Real shifts in CoreStack are real
   events of unknown cause.
5. The ledger delays but does not prevent absorption; a persistent attacker level is eventually adopted (and logged).
6. Rollback keeps a stronger line on attack absorption on NAB (median 0.17 at +60 d) at the price of resolving fewer legitimate
   shifts (44%); the proposed design sits at a different point on that trade-off, not above it on every axis.
7. The stable label threshold (1 hour-scale unit) and the 5% operating point were fixed before the fresh run; changing either
   after seeing fresh results would invalidate it.
8. Software/mathematical-method objections: word the claims around stored system state and operations (snapshot, hold, shadow,
   ledger, restore point) and the measured integrity/availability effect.
