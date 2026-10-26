# Knowledge-base authoring

The knowledge base is static, version-controlled YAML. Runtime explanation,
recommendation, and mitigation code must not call an LLM or external API.
Entries are advisory text: they must not assert that an attack is known, alter
scores/severity, or trigger remediation.

## Files and entry shapes

- `phase3/knowledge/knowledge_base.yaml` contains `kb_version`, generic
  `causes`, and threat-specific entries.
- `phase3/knowledge/threat_signatures.yaml` contains deterministic matcher
  conditions. Keep match requirements grounded in signals the case actually
  carries.
- Each cause includes its category, title, definition, how it appears,
  common causes, why it matters, limitations, further reading, and
  `recommended_checks`.
- Each threat entry includes a definition, observed indicators, false-positive
  notes, limitations, further reading, investigative checks, resolution
  criteria, MITRE ATT&CK references (if verified), and immediate, short-term,
  and hardening guidance. Provider-specific mitigation text is optional; the
  generic text is required.

## Safe text and placeholders

Use plain text in YAML. Template interpolation uses
`string.Template.safe_substitute`; never use `str.format`, f-strings, `eval`,
or HTML rendering for knowledge text. The only approved knowledge-base
placeholders are:

`entity_id`, `cloud_provider`, `region`, `final_score`, `severity`,
`deviation_score`, `drift_score`, `similarity_score`, `group_size`, and
`top_changed_feature`.

Treat substituted values as untrusted text. Do not add a placeholder merely
because a value is available in the case; update the explicit whitelist and
its tests only after a security and contract review.

## Validation before merge

1. Add or update generic fallback content so unknown categories still render
   complete recommended checks.
2. For a threat, add matcher coverage for positive and negative evidence and
   provider coverage for each supported provider.
3. Verify provider text falls back to the generic step when no variant exists.
4. Add a safe-rendering test for any new interpolated field and preserve the
   `UNKNOWN` fallback.
5. Run:

```powershell
python -m pytest -q tests/unit/phase3/knowledge
```

Do not include demo ground-truth labels in an API contract, `RCACase`,
`Explanation`, or alert payload.
