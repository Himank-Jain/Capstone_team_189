# Component ablation from the frozen-design runs (no new runs)

Cells: dev / fresh where both exist. Source: `FINAL_TABLES.md`. Intervals are in that file. NAB = day-resampled replicas, synthetic
order, dependent entities; CoreStack = real Azure telemetry. All attacks are team-generated.

| Variant | Parts present | False alerts | 2σ stealth detected | Poisoned calibration caught | Growth unresolved |
|---|---|---|---|---|---|
| Clipped CUSUM | trigger only, no hold of a validated bound, no ledger | NAB 3% / CS 0% | 92% / 65% | 95% / 66% | 84% / 69% |
| Validated bound + hold | bound, hold, shadow; promotion only by the old cohort-agreement rule, which did not resolve growth (100% unresolved) | 10% / 8% | 8% / 14% | 99% / 98% | 100% / 100% |
| Validated bound + hold + ledger | adds capped promotion and ledger | 10% / 8% | 8% / 14% | 99% / 98% | 41% / 25% |
| CUSUM trigger + validated reference + ledger | sequential trigger, hold, shadow, ledger | 4% / 0% | 92% / 68% | 97% / 68% | 9% / 64% |
| Dual trigger, no ledger | both triggers, hold, shadow; same old promotion rule | 10% / 8% | 94% / 68% | 100% / 98% | 100% / 100% |
| **Dual trigger + ledger (proposed)** | all | 10% / 8% | 94% / 68% | 100% / 98% | 6% / 25% |

(NAB dev / CoreStack dev in each cell.)

## What each part buys, as measured

* **Validated bound and hold** supply poisoned-calibration catching (66% to 98% on CoreStack dev against the trigger alone) and
  nothing for stealth ramps on their own (8% on NAB dev).
* **The sequential trigger** supplies stealth detection (8% to 94% on NAB dev; 14% to 68% on CoreStack dev).
* **The ledger** supplies resolution of growth (100% unresolved to 6% on NAB dev; 100% to 25% on CoreStack dev) and does not
  change detection or false alerts.
* **No single part does all three.** The trigger alone misses poisoned calibration on real data and never resolves growth; the
  bound alone misses stealth ramps; neither resolves growth without the ledger. This is the argument that the combination is
  more than a list of parts, but it rests on dev data and the interaction itself (as opposed to additive effects) has not been
  tested.

## Not run

Hold without a shadow, a shadow without a hold, an unvalidated bound on the frozen design (an earlier ablation gave 21/21 vs 1/21
on NAB and 39/39 vs 28/39 on CoreStack), and any variant on fresh data beyond what `FINAL_TABLES.md` already contains.
