# CoreStack real-data evidence (control-plane corroboration pivot)

Data: 239 series / 62 Azure resources, 90 contiguous days, plus 4,593 daily activity-log rows (CoreStack-provided; not committed).
Natural onset = sustained level shift (>=3 robust units, same side the next week). Random onsets = same series, random days (what an unexplained, e.g. data-plane, shift looks like).

| Anchor | Natural shifts | Random placement | Lift |
|---|---|---|---|
| Control-plane change event within +/-3 d | 20.2% (n=114, 30 resources) | 6.4% | 3.1x |
| Cohort co-shift (>=30% peers, all subs) | 28.9% | 30.7% | 0.9x (no signal) |
| Cohort co-shift (same subscription) | 48.4% | 43.9% | 1.1x (no signal) |
| Change AND cohort | 7.0% | 1.6% | 4.4x |

Earlier alignment test (corestack_alignment.json): change 18.8% vs null 4.3%; read-event control 27.3% vs 14.5% (also lifts, ~1.9x), so the effect is not purely causal-semantic.

## Reading
- Change events carry real but modest information: 3x lift, only ~20% sensitivity. Alone they cannot gate promotion (they would block ~80% of real shifts); as an extra *sufficient* path (promote if cohort OR change-event) they add a low-false-anchor route (6% by chance).
- Cohort agreement does NOT discriminate on this data (cohort co-movement is common in random windows). The cohort promotion rule's real-data support is therefore unproven; its NAB support is synthetic-cohort only.
- The read-event control also lifts, so "corroboration by causal change" is not demonstrated; only "activity coincides with shifts".
- Conclusion: the pivot is NOT proven as an irrefutable inventive step. Do not claim it as a lead claim.
