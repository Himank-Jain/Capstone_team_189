# Threat signature library

The threat matcher is a deterministic evidence matcher, not an attack
classifier. Its signatures live in
[`phase3/knowledge/threat_signatures.yaml`](../phase3/knowledge/threat_signatures.yaml);
the corresponding explanation, investigation checks, mitigation guidance,
provider variants, and resolution criteria live in
[`phase3/knowledge/knowledge_base.yaml`](../phase3/knowledge/knowledge_base.yaml).
Scenario labels are test/demo expectations only and are not returned in
incident, RCA, or explanation responses.

## Current behavior

- A signature can match only from observed metric-family directions,
  provider/entity/namespace context, component scores, and (where configured)
  similar-episode severities.
- A LOW-confidence match remains generic guidance. MEDIUM and HIGH matches may
  select threat-specific explanation and investigative checks.
- Match wording is hedged ("possible", "pattern consistent with"); a match is
  not a diagnosis and does not change anomaly score or severity.
- No knowledge or mitigation step executes a cloud action. Connectors remain
  read-only and mitigation is advisory.
- Missing or unrecognized evidence uses the complete `UNKNOWN` entry and
  keeps `is_fallback=true`.

## Existing signature identifiers

The YAML file is the source of truth for the complete identifier set. It
currently includes signatures for credential theft, insider threat, network
scan, malware execution, ransomware, data exfiltration, volumetric DDoS, public
exposure, brute-force login, lateral movement, log tampering, rogue resources,
and function abuse. Do not infer that every synthetic scenario is guaranteed
to match its similarly named signature; rules and input vocabulary determine
the actual result.

## Verification

Run focused matcher, knowledge, provider-matrix, and scenario tests:

```powershell
python -m pytest -q tests/unit/phase3/knowledge
```

The knowledge tests validate signature coverage, required advisory sections,
provider variants, placeholder safety, and fallback behavior. Add a matcher
test and a knowledge entry when adding a signature; do not change a signature
to force a demo scenario to a desired category without reviewing its evidence.
