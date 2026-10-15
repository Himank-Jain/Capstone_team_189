# Scenario pipeline outcomes

Observed by running each data-driven scenario through `POST /demo/generate/alert` and Phase 3 RCA using the current `hypothesis_rules.yaml`; scenario IDs and expected categories are test inputs, not rules or API-result fields.

| Scenario | Group | Expected cause (test only) | Actual hypothesis | Severity | Minimum target | Meets target |
|---|---|---|---|---|---|---|
| `credential_theft` | Malicious | BEHAVIOR_CHANGE | UNKNOWN | MEDIUM | MEDIUM | Yes |
| `insider_threat` | Malicious | CONFIGURATION_CHANGE | UNKNOWN | MEDIUM | MEDIUM | Yes |
| `network_scan` | Malicious | — | UNKNOWN | MEDIUM | MEDIUM | Yes |
| `malware_execution` | Malicious | RESOURCE_CHANGE | UNKNOWN | MEDIUM | MEDIUM | Yes |
| `ransomware` | Malicious | BEHAVIOR_CHANGE | DRIFT | HIGH | MEDIUM | Yes |
| `data_exfiltration` | Malicious | TRAFFIC_CHANGE | BEHAVIOR_CHANGE | CRITICAL | MEDIUM | Yes |
| `ddos_volumetric` | Malicious | TRAFFIC_CHANGE | DRIFT | HIGH | MEDIUM | Yes |
| `public_exposure` | Malicious | CONFIGURATION_CHANGE | RESOURCE_CHANGE | LOW | MEDIUM | No |
| `brute_force_login` | Malicious | BEHAVIOR_CHANGE | DRIFT | HIGH | MEDIUM | Yes |
| `lateral_movement` | Malicious | TRAFFIC_CHANGE | DRIFT | HIGH | MEDIUM | Yes |
| `log_tampering` | Malicious | CONFIGURATION_CHANGE | RESOURCE_CHANGE | LOW | MEDIUM | No |
| `rogue_resources` | Malicious | RESOURCE_CHANGE | RESOURCE_CHANGE | LOW | MEDIUM | No |
| `function_abuse` | Malicious | TRAFFIC_CHANGE | DRIFT | HIGH | MEDIUM | Yes |
| `benign_baseline` | Benign | — | RESOURCE_CHANGE | LOW | LOW | Yes |
| `planned_deployment` | Benign | — | RESOURCE_CHANGE | LOW | LOW | Yes |
| `organic_growth` | Benign | — | RESOURCE_CHANGE | LOW | LOW | Yes |
| `provider_regional_event` | Benign | — | RESOURCE_CHANGE | LOW | LOW | Yes |
| `ambiguous_change` | Ambiguous | — | UNKNOWN | MEDIUM | LOW | Yes |

Cause-category differences are reported, not forced. A severity target miss is retained in the table and should not be interpreted as a confirmed threat label.
