# CAPSTONE-189 Final Project Report

## Scope and outcome

The approved cleanup establishes one canonical source tree for the local
synthetic anomaly-detection demo. The Phase 0-3 implementation, provider
connectors, migration environment, scripts, demo generator, and demo API now
live under their canonical package paths. The obsolete sibling
`Capstone_final` tree was compared and removed after its useful source files
were confirmed at their canonical destinations.

The registered synthetic model bundle was preserved. The manifest continues
to point to the checkpoint and FAISS index under
`model_registry/synthetic_32/`; `model_registry/tstcc_encoder_final.pt` and
`model_registry/artifacts_manifest.json` were not removed.

## Canonical layout

The project root retains `phase0/`, `phase1/`, `phase2/`, `phase3/`,
`live_ingestion/`, `shared/`, `config/`, `tests/`, `scripts/`, `notebooks/`,
`frontend/`, `demo_generator/`, `alembic/`, `alembic.ini`,
`docker-compose.yml`, `requirements.txt`, `.env.example`, `README.md`,
`.gitignore`, `conftest.py`, and `pytest.ini`. Supporting documentation is in
`docs/`; generated model bundles stay local under `model_registry/`.

- Provider implementations are in `live_ingestion/connectors/`.
- The FastAPI demo app and domain routers are in `phase3/api/`.
- Database migration files are in root `alembic/`.
- Operational and legacy-specific command-line tools are in `scripts/`.
- The former `demo-generator/` path is consolidated as `demo_generator/`.
- Compatibility shims were removed after imports were updated.

## Verification

Latest recorded checks for this cleanup:

| Check | Result |
|---|---|
| Python 3.10.11 full suite | **323 passed, 1 skipped, 1 warning** |
| Scoped Flake8 (`phase1 phase2 phase3 shared scripts`) | **0 diagnostics** |
| Frontend `npm ci`, lint, typecheck, Vitest, production build | **Passed in an isolated validation copy; 10 tests** |
| Playwright mock-mode routes and onboarding flow | **16 passed** |
| Fresh temporary SQLite `alembic upgrade head` and `alembic check` | **Passed; no schema drift** |
| Synthetic demo (`amazon`, `credential_theft`, `PAGE`) | **Passed; alert accepted and RCA generated** |
| `git diff --check` | **Passed** |

Run the required demo from the repository root:

```powershell
python scripts\run_local_demo.py --tenant amazon --scenario credential_theft --channel PAGE
```

The demo uses synthetic data and local PAGE notification behavior. Live cloud
credentials, production Postgres deployment, and external SMS, webhook, or
PagerDuty delivery are not configured by this flow.

The source frontend's existing `node_modules` was incomplete (`tsc` was
missing), so the clean `npm ci` and frontend validations ran in a temporary
copy instead of replacing dependencies used by the active local frontend.
`npm ci` reported 10 dependency audit advisories (5 moderate, 3 high, 2
critical); dependency remediation was not part of this cleanup.

## Remaining limitations

- Phase 0 statistical scores are not yet attached to Phase 3 `RCACase` records.
- A real held-out-batch collapse diagnostic was not available for verification.
- The synthetic threat-signature report is not a production accuracy claim:
  Top-1 is 14/18 and Top-3 is 15/18; three scenarios miss their minimum
  severity target.
- This acceptance verifies the local PAGE path, not external email/Slack
  delivery or production cloud credentials.

## Generated data and regeneration

Intermediate corpus data, local databases, logs, caches, and frontend build
output are disposable and ignored by Git. The registered
`model_registry/synthetic_32/` bundle is intentionally preserved. See
[`model_registry/README.md`](model_registry/README.md) for the regeneration
workflow and its compatible-input requirements.

The final cleanup removed the root local demo database, 34 generated email
logs, frontend `dist/` and Playwright `test-results/`, `.pytest_cache/`, and
60 Python `__pycache__/` directories. Temporary validation databases and the
isolated frontend validation copy were also removed. Installed
`frontend/node_modules/` was left in place to avoid disrupting the running
local frontend. The superseded sibling reconciliation assessment was removed;
its current limitations and verification evidence are recorded here instead.

## Preserved boundaries

- Its useful source files and supported configuration were verified against
  their canonical destinations before the sibling directory was removed.
- The unused Python 3.14 environment was removed. The active Python 3.10
  environment remains outside the repository at
  `C:\Users\Himank\Desktop\Capstone\.venv310`; recreate a project environment
  from `requirements.txt` when needed.
- Python virtual-environment contents were not copied between 3.14 and 3.10:
  they are interpreter-specific and can be recreated from the canonical
  dependency manifest.
- No remote push, merge into `dev`/`main`, or commit was performed.
- The active registered model bundle and its manifest references were retained.
