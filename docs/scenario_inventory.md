# Synthetic scenario inventory

## Existing repository inventory

The initial tree did not contain eight distinct runnable scenarios. It
contained eight declarations split across two sources: three hardcoded
`DemoGenerator` declarations and five YAML fragments. Three IDs were
duplicated between those sources, leaving five distinct IDs. The API separately
exposed those three hardcoded IDs plus `benign_baseline`, and the React control
panel loaded that four-item API list.

| Existing ID | Definition before this change | Existing meaning | Control panel before this change |
|---|---|---|---|
| `credential_theft` | `demo_generator/generator.py` and `scenarios/credential_theft.yaml` | Unusual authentication activity | Yes |
| `insider_threat` | `demo_generator/generator.py` and `scenarios/insider_threat.yaml` | Unusual trusted-user behavior / drift | Yes |
| `network_scan` | `demo_generator/generator.py` and `scenarios/network_scan.yaml` | Repeated resource-description requests | Yes |
| `malware_execution` | `demo_generator/scenarios/malware_execution.yaml` | Sustained compute increase | No |
| `ransomware` | `demo_generator/scenarios/ransomware.yaml` | Storage write/delete activity | No |
| `benign_baseline` | `phase3/api/app.py` | Low-activity baseline | Yes |

`demo_generator/generator.py` was the only source used by the Python
`DemoGenerator`; the five scenario YAML fragments were not loaded by it. The
control panel obtains its options from `GET /demo/scenarios` and injects via
`POST /demo/generate/alert`.

## Canonical scenario library

The canonical definitions are now in `demo_generator/scenarios/library.yaml`.
`ScenarioSpec` and `MetricSignature` are package-local contracts in
`demo_generator/types.py`; no shared contract was modified. The loader checks
the YAML structure and reads the trained metric vocabulary before generating
events. Adding a scenario requires a YAML entry, not a generator-code branch.

Existing scenarios were extended instead of duplicated:

| Canonical existing ID | Expanded scenario intent |
|---|---|
| `credential_theft` | Credential compromise and unusual authentication/API activity |
| `insider_threat` | Policy/privilege misuse and unusual access patterns |
| `network_scan` | Reconnaissance and east-west connection activity |
| `malware_execution` | Compute resource abuse, including cryptomining-like CPU/egress activity |
| `ransomware` | Mass storage overwrite/delete behavior |
| `benign_baseline` | Stable baseline |

The library adds these distinct scenarios: `data_exfiltration`,
`ddos_volumetric`, `public_exposure`, `brute_force_login`,
`lateral_movement`, `log_tampering`, `rogue_resources`, `function_abuse`,
`planned_deployment`, `organic_growth`, `provider_regional_event`, and
`ambiguous_change`. `credential_theft` corresponds to the suggested
`CRED_COMPROMISE`, while the existing insider, malware, and ransomware
scenarios cover the suggested privilege-escalation, cryptomining, and
ransomware-delete ideas; separate overlapping entries were not added.

The React control panel groups entries as Malicious, Benign, and Ambiguous and
lets the operator select a provider and intensity. Scenario labels are control
inputs only: injection responses and persisted RCA data do not include the
selected scenario ID or ground-truth category.

## Important scope notes

- Scenario output is synthetic `RawRecord` event data with
  `cloud`, `entity_type`, `namespace`, `metric_name`, and `value`.
- Unmapped metric families are skipped and logged. No metric name is invented.
- The trained bundle's cloud vocabulary omits OCI. OCI is selectable for
  synthetic coverage, but the categorical cloud feature may map to UNK.
- Minimum severity values in the YAML are test targets, not detector guarantees.
- Expected cause categories are held in test/report logic only. Rules are not
  altered to force a particular scenario-to-cause result.
- These scenarios are functional test fixtures, not ground-truthed attack data
  or evidence of detection accuracy.
