# CAPSTONE-189

AI-assisted, multi-cloud anomaly and security-alerting capstone. The runnable synthetic demo combines the existing Phase 2 scoring/alerting path with Phase 3 deterministic RCA, knowledge guidance, onboarding, and an investigation dashboard.

## Current Status

- Synthetic end-to-end flow: tested.
- Phase 0-3 Python suite: `214 passed` on both Python 3.10.11 and diagnostic Python 3.14.3.
- Dashboard production build: passed.
- Live cloud credentials, Postgres deployment, and external SMS/Webhook/PagerDuty delivery: not configured by the synthetic demo.
- `Capstone_team_189/` remains as a preserved Git source tree; Phase 3 source/tests were merged into this runnable tree, but conflicting legacy files were not wholesale overwritten.

See [the end-to-end assessment](docs/END_TO_END_PROJECT_ASSESSMENT.md) for the full stack, module/function map, data flow, sister-tree reconciliation, verification evidence, and prioritized gaps. See [the final project working report](FINAL_PROJECT_REPORT.md) for the current planner comparison, runtime results, and remaining gaps.

## Quick Start

From this directory, install Python requirements and start the backend from the project root so relative rule/config paths resolve:

```powershell
python -m pip install -r requirements.txt
$env:CAPSTONE_DATABASE_URL = 'sqlite:///./capstone_phase3_live_demo.db'
python -m uvicorn backend.api_demo_ext.app:app --host 127.0.0.1 --port 8001
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173/`. The backend API documentation is at `http://127.0.0.1:8001/docs`.

To use frontend fixtures without a backend, set `VITE_MOCK_MODE=true` in `frontend/.env`; set `VITE_API_BASE` to override the API URL. A template is provided in `frontend/.env.example`.

## Main Components

- `phase0/`: streaming, bucketing, rolling baselines, seasonality, and statistical scoring.
- `phase1/`: historical corpus, contrastive encoder, FAISS indexing, and model registry.
- `phase2/`: ingestion, encoding, anomaly/drift/episode scoring, alerting, deduplication, escalation, and notification interfaces.
- `phase3/`: platform schema, identity, cloud-connect services, onboarding, notifications, deterministic RCA, knowledge base, and security helpers.
- `backend/api_demo_ext/`: FastAPI demo API and Phase 3 adapter routes.
- `frontend/`: React/TypeScript dashboard, demo controls, onboarding, connections, incidents, and RCA screens.
- `demo_generator/`: canonical importable synthetic scenario generator; `demo-generator/` retains a compatibility launcher/scenario scaffold.
- `tests/`: unit, API, and integration coverage.

## Verification

```powershell
python -m pytest -q
python -m pip check
cd frontend
npm run build
```

Use read-only cloud identities and dry-run mode before configuring any live connector. The demo's connections view reports channels requiring provider credentials; it does not claim those providers are delivering.
