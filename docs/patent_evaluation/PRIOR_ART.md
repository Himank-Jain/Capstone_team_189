# Prior-art search and closest-art analysis (working document for the patent attorney)

**Scope and limits.** This is a desk search done with a web search engine and the Google Patents pages it returned. It is not a
formal novelty search: no USPTO/EPO/WIPO full-text claim search, no classification-based search (G06N, G06F21/55, H04L9/40,
G06F11/34), no non-English literature, and for several patents only the description, not the claims, was read. Items marked
"second-hand" were seen only through a survey page; items marked "not read" could not be opened. A professional search should
be commissioned before filing. Nothing here is legal advice.

## 1. What is already known (element by element)

| Element of our system | Where it is already known | Consequence |
|---|---|---|
| Sequential change detection on a residual (CUSUM) | Page, *Biometrika* 1954; Page–Hinkley; ADWIN (concept-drift literature, e.g. "Learning under Concept Drift: A Review", arXiv 2004.05785) | Not novel on its own. Our trigger is a textbook CUSUM. |
| Adaptive behavioural baselines that learn from new data | Netskope US10270788 (online streaming learner, "old unusual patterns become the new norm if they persist"); Splunk/Cisco US9516053 ("baseline profiles can be continuously updated"); Darktrace US12223046 (self-learning "pattern of life... dynamically updated") | The vulnerability we address is the disclosed normal operating mode of these systems. |
| Updating the baseline only after the change is judged legitimate | US9516053 describes updating a baseline when the behaviour change "has been resolved and deemed legitimate" by the platform or an administrator | **Closest conceptual art for hold-then-promote.** It gives no shadow state, no cap, no evidence weighting, no attribution to a trusted snapshot. |
| Candidate/shadow model compared with the incumbent, then kept or discarded | PurePredictive WO2017201107 (retrain module, A/B trial of retrained vs original, keep the better); "challenger" patterns in ML-ops generally; arXiv 2609.04388 on conditional validation before promoting candidates in adaptive intrusion detection (title/abstract seen only, **PDF not readable, must be read**) | Shadow-and-promote by accuracy is known. Ours promotes on baseline-state stability and evidence, which is not accuracy-based, but an examiner will cite these. |
| Bounding the influence of each update; attacker gain bounded by constraints | Kloft & Laskov, *Security Analysis of Online Centroid Anomaly Detection*, JMLR 13 (2012), and AISTATS 2010: poisoning of online centroid detectors; with external constraints the attacker's gain has a strict upper bound; bounded false-positive rate | Bounded influence of a poisoning attacker is **known and analysed**. Our headline "bounded drift" cannot be claimed as such. |
| Stealth/gradual poisoning ("frog-boiling") defeats per-update outlier rejection, history bounds, Kalman prediction and reputation | Chan-Tin, Heorhiadi, Hopper, Kim, *The Frog-Boiling Attack*, SecureComm 2009 / ACM TISSEC 2011; Rubinstein et al., ANTIDOTE, IMC 2009 (PCA subspace detectors poisoned over weeks; robust-PCA defence); Kravchik & Shabtai, "Can't Boil This Frog" (arXiv 2002.02741); Kravchik, Biggio, Shabtai (arXiv 2012.15740, 2020) | The attack is well documented. Our motivation is not new; our defence has to differ from rejection, bounding and robust statistics. |
| Selective updating from recent, sufficiently similar samples; memory filtering; consensus; quarantine mixtures | FITNESS, MemStream, CIoTA, Xiang & Miller (second-hand, via the Lacuna survey page) | Update-filtering defences exist. None seen holds updates into a shadow and promotes by capped steps. |
| Rollback/checkpoint of model state | General software practice; our own comparator `rollback`; no detector-specific patent read | Treat as known. |

Searched families: poisoning of online/adaptive anomaly detectors; clipping/bounded updates; change-point/concept-drift detection;
checkpoint and rollback; UEBA/AIOps vendor patents (Netskope, Splunk/Cisco, Darktrace, PurePredictive read in part; Exabeam,
Securonix, Microsoft, Amazon, Google, IBM, Dynatrace, Datadog, Moogsoft **not searched in depth**).

## 2. Closest art, gap by gap

| Feature of the proposed combination | Kloft–Laskov 2012 | Frog-boiling / ANTIDOTE | US9516053 (Splunk) | US10270788 (Netskope) | US12223046 (Darktrace) | WO2017201107 (PurePredictive) |
|---|---|---|---|---|---|---|
| Baseline held while a sequential detector reports departure from a *trusted snapshot* | no (analyses update rules) | no (shows existing defences fail) | no | no | no | no |
| Shadow baseline learns during the hold | no | no | no | no | no | partly (retrained model trial) |
| Promotion in a *capped step*, cap grows with *independent evidence* | no | no | no (binary, operator) | no | no | no |
| Retroactive, reversible provenance ledger of every promotion | no | no | no | no | no | no (evaluation metadata only) |
| Calibration validated before use (alert exclusion, trend, cohort cross-check, cohort fallback) | no | robust statistics, not validation | no | no | no | partly (training-data range checks) |
| Attribution of a deviation against the trusted baseline state | no | no | no | no | no | no |
| Technical effect: bounded silent displacement before first alert, legitimate growth still resolves | bounded attacker gain (analysis), no resolution mechanism | n/a | no | no | no | no |

No single reference discloses the evidence-weighted capped ledger or the validated-calibration-plus-trigger-reference
combination. Every individual *concept* (hold, shadow, promote, CUSUM, bounded influence, rollback, operator-confirmed update)
appears somewhere. **The combination therefore has to be argued as a synergy with a measured effect, not as a collection of
new parts.**

## 3. Problem–solution framing (EPO style)

* **Closest prior art:** online anomaly detection with adaptive baselines under poisoning (Kloft–Laskov for the formal setting;
  US9516053 for the deployed hold-until-judged-legitimate pattern).
* **Distinguishing features (candidate independent claim):** (a) a trusted baseline snapshot stored as system state;
  (b) a sequential detector on the residual against that snapshot that switches the entity's baseline from update to hold and
  routes readings to a shadow baseline; (c) calibration of the detector reference validated before use, with fall-back to a
  snapshot-anchored reference when validation fails; (d) promotion of the shadow baseline in steps whose size is capped by an
  allowance built from independent evidence and which never exceed the allowance without an operator; (e) a persisted
  provenance record per promotion that allows each step to be reverted and the affected alerts re-scored.
* **Technical effect (measured, see RESULTS):** the baseline state held in the monitoring system is displaced by less than a
  stated amount before the first alert, while legitimate sustained changes are still absorbed within a bounded number of days,
  with every absorbed step recoverable. That is an integrity property of stored state in a computer system, not a mathematical
  result as such.
* **Objective technical problem:** how to keep an adaptive baseline usable (it must follow legitimate change) without letting a
  slow adversary, or the attacker's own calibration period, rewrite it undetected.
* **Why not obvious (to be argued, not assumed):** the literature treats poisoning defence and drift adaptation as opposed
  (the Lacuna survey describes the "drift-versus-poisoning tradeoff"). In our frozen-design evaluation the comparators sit at
  one end or the other: frozen and rollback keep attacks out but leave legitimate shifts unresolved (frozen 80% / 88% / 61% of
  flagged legitimate growth still unresolved on NAB dev / NAB fresh / CoreStack dev; rollback 49% / 27% / 52%); adaptive and
  clipped-CUSUM detect or absorb but never close the alert (CUSUM 84% / 83% / 69% unresolved). The proposed combination is the
  only tested strategy with detection at the level of the best detector at a matched false-alert rate, poisoned-calibration
  detection of 98–100%, and 0–25% of legitimate growth unresolved (6% / 0% / 25%). Counter-argument an examiner will make: "a
  person skilled in the art would add a shadow model to a CUSUM-frozen detector, as PurePredictive does, and promote on operator
  confirmation, as Splunk does." The answer must rest on the *evidence-built, step-limited* promotion with a *restore point per
  step* and on the *validated, snapshot-anchored reference*, and the ablations show what each part buys: without the ledger
  (`dual_noledger`) legitimate growth stays 100% unresolved; without validating the bounds, poisoned calibration is caught by 1 of 21 held-out
  NAB entities against 21 of 21 with validation, and by 28 of 39 against 39 of 39 on CoreStack (earlier ablation run, before the
  design freeze). Anchoring the CUSUM reference to the snapshot when validation fails adds little (CoreStack dev 66% for clipped
  CUSUM, 68% with the anchored reference); the poisoned-calibration effect comes from the validated *bounds*.
* **Evidence limits that weaken this argument:** attacker levels are absorbed within about 60 days of the first alert (the
  ledger is a delay, not a barrier); the proposed design does not beat rollback on attack absorption, only on resolution; the
  fresh CoreStack sample of clean series is 8.

## 4. Recommendations

1. Commission a formal search on G06N/G06F21/55 with the claim vocabulary: "snapshot", "shadow", "promotion", "allowance",
   "ledger", "baseline", "adversarial/poisoning", and read the claims of US9516053, US10270788, US12223046, WO2017201107 in full.
2. Obtain and read arXiv 2609.04388 and the full text of Kloft & Laskov for their defence recommendations.
3. Keep the independent claim at the level of the mechanism (items (a)–(e) above), not at "holding updates when drift is detected".
4. Write the claims around stored system state and system operations (store snapshot, hold, shadow, promote with a persisted
   record, restore), with the statistics in dependent claims.
5. Disclose and describe the failure modes honestly in the specification (slow absorption of a stable shifted level) rather than
   claim that attacks are never absorbed.

## 5. Search log (second pass, 15 October 2026)

All searches were run through a general web search engine that returns Google Patents, Justia, USPTO PPUBS and arXiv pages. No
patent-office classification search tool was available. **No classification-based or full-text claim search was possible, so this
is still not a formal search.**

| # | Search string (abridged) | Result |
|---|---|---|
| 1 | patent anomaly detection baseline "shadow" baseline hold update promote ledger rollback restore point poisoning | Only blockchain-ledger and microservice patents; none on baseline governance. |
| 2 | patent behavioral baseline update frozen while anomaly detected, trusted snapshot, gradual drift poisoning adaptive baseline | US9544321B2 (Securonix); Slips HTTPS adaptive-baseline blog; none with snapshot or hold. |
| 3 | calibration period validation poisoning anomaly detector threshold bound cohort fallback online learning defense | Kloft & Laskov, Rubinstein et al. (already known); two 2026 arXiv items on self-poisoning in adaptive OOD detection and memory poisoning (titles only, not read). |
| 4 | US patent "baseline" "snapshot" anomaly detection "update" suspended "shadow model" candidate promoted only after validation | US8887286B2 (opened, see below); US20170063905A1 and about eight other result titles were not opened. None of those opened describes a shadow baseline. |
| 5 | "data poisoning" anomaly detection "gradual" "baseline" patent claims "limiting the rate" of baseline change | US12405930B2, US12423280B2 (Dell): poisoned-data curation; Berkeley "stealthy poisoning" reports. |
| 6 | arXiv 2609.04388 (direct fetch and search) | **Not readable.** The abstract page returns an empty PDF placeholder; the API host disallows the fetch. Still unread. |

Classes that a formal search should cover: G06N 20/00, G06N 3/08 (training, poisoning), G06F 21/55 (detecting local intrusion
or anomalies), G06F 21/56, H04L 63/1425 (traffic anomaly), H04L 41/16 and G06F 11/34 (monitoring, AIOps).

### New references read in this pass (description pages only, claims not fully read)

| Reference | What it shows | Differs from the proposal |
|---|---|---|
| US9544321B2 Securonix, "Anomaly detection using adaptive behavioral profiles" (priority 2015-01-30) | Profile adapted by exponential decay (14-day half-life). Dependent claims: only observations with low anomaly probability update the profile; outliers go to threat analysis. | **Outlier-gated updating is known**; a slow attacker stays inside the gate (this is the frog-boiling attack). No snapshot, bound on displacement, shadow, capped promotion, ledger or restore point. |
| US8887286B2 Allied Security Trust / Adobe, continuous anomaly detection | Continuously maintained behavioural model; persisted history of model versions and decisions, audit trail. | A record of model versions is known in general. No hold of the baseline, validated bound, shadow or capped step. An examiner may cite it against the ledger element on its own. |
| US12423280B2 and US12405930B2, Dell, poisoned-data identification during data curation | Anomaly detection and optimisation to find poisoned data before storage; remedial actions. | Acts on incoming data sets, not on a stored per-entity baseline; no hold, shadow, cap or revertible record. |

### Differs-from rows for every reference found

| Reference | Validated bound + hold (claim 1) | Shadow + capped promotion + ledger (claim 2) |
|---|---|---|
| Page 1954 (CUSUM) | trigger only; no stored baseline | n/a |
| Kloft & Laskov 2012 | analyses bounded influence; no calibration validation, no hold | no |
| Rubinstein 2009, Chan-Tin 2009/2011 | robust estimation; no hold | no |
| Kravchik et al. | attack analysis | no |
| US9516053 Splunk/Cisco | hold-until-judged-legitimate, no bound or calibration validation | binary, operator-driven; no shadow, cap or restore |
| US9544321 Securonix | outlier-gated update; no bound or validation | no |
| US10270788 Netskope; US12223046 Darktrace | adaptive baselines; no governance | no |
| WO2017201107 PurePredictive | training-data range checks | A/B trial by accuracy; no cap, ledger |
| US8887286 Allied/Adobe | none | persisted model history; no cap or restore point |
| US12423280 / US12405930 Dell | data-curation screening, not baseline state | no |
| arXiv 2609.04388 | **not read** | **not read** |

**Statement for the file.** In the searches above nothing closer than US9516053 (hold-until-legitimate) and Kloft & Laskov
(bounded influence) was found, but the search was not formal and one candidate reference could not be read; this is not a finding
that nothing closer exists.
