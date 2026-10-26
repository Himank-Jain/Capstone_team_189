# Threat signature accuracy against WP-A synthetic scenarios

Evaluated 18 WP-A scenarios through `POST /demo/generate/alert`,
then matched the persisted RCACase. Expected scenario outcomes are used
only by this evaluation script; the matcher receives no scenario ID,
display name, category, or demo label. The deliberately ambiguous
scenario is a correct result only when no threat signature matches.

This is synthetic-corpus agreement, not an out-of-sample accuracy claim.
Signatures were authored from the stated threat behaviors and existing
metric-family evidence, not tuned to these evaluation outcomes. Unmapped
families remain absent rather than being assigned proxy metrics.

- Top-1: 14/18 (77.8%)
- Top-3: 15/18 (83.3%)

| WP-A scenario (evaluation only) | Expected outcome | Ranked matches | Top-1 rate | Top-3 rate |
|---|---|---|---:|---:|
| `credential_theft` | `credential_theft` | credential_theft (HIGH) | 100% | 100% |
| `insider_threat` | `insider_threat` | insider_threat (HIGH), data_exfiltration (HIGH) | 100% | 100% |
| `network_scan` | `network_scan` | network_scan (HIGH), lateral_movement (HIGH) | 100% | 100% |
| `malware_execution` | `malware_execution` | malware_execution (HIGH), ambiguous_change (HIGH), planned_deployment (HIGH) | 100% | 100% |
| `ransomware` | `ransomware` | ransomware (HIGH), organic_growth (HIGH) | 100% | 100% |
| `data_exfiltration` | `data_exfiltration` | data_exfiltration (HIGH), insider_threat (HIGH) | 100% | 100% |
| `ddos_volumetric` | `ddos_volumetric` | ddos_volumetric (HIGH), provider_regional_event (HIGH) | 100% | 100% |
| `public_exposure` | `public_exposure` | no threat match | 0% | 0% |
| `brute_force_login` | `brute_force_login` | brute_force_login (HIGH) | 100% | 100% |
| `lateral_movement` | `lateral_movement` | lateral_movement (HIGH), network_scan (HIGH) | 100% | 100% |
| `log_tampering` | `log_tampering` | no threat match | 0% | 0% |
| `rogue_resources` | `rogue_resources` | no threat match | 0% | 0% |
| `function_abuse` | `function_abuse` | function_abuse (HIGH) | 100% | 100% |
| `benign_baseline` | `benign_baseline` | benign_baseline (HIGH), organic_growth (MEDIUM) | 100% | 100% |
| `planned_deployment` | `planned_deployment` | planned_deployment (HIGH), ambiguous_change (HIGH), malware_execution (MEDIUM) | 100% | 100% |
| `organic_growth` | `organic_growth` | benign_baseline (HIGH), organic_growth (MEDIUM) | 0% | 100% |
| `provider_regional_event` | `provider_regional_event` | provider_regional_event (MEDIUM), ddos_volumetric (MEDIUM) | 100% | 100% |
| `ambiguous_change` | UNKNOWN (no threat match) | no threat match | 100% | 100% |

Generated at 2026-10-14T15:55:33+05:30.
