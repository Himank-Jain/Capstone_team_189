# CAPSTONE-189 Dashboard Demo

## Overview

This frontend is the Vite + React dashboard for the CAPSTONE-189 demo API. In addition to the live demo controls and alert feed, it includes a resumable onboarding wizard, synthetic connection status, an incident/RCA list, and structured incident investigation views.

## Folder Structure

- `src/app/demo/page.tsx` — Demo control page with tenant and scenario selection.
- `src/app/onboarding/page.tsx` — Resumable onboarding steps with an explicit live-monitoring confirmation.
- `src/app/incidents/` — Tenant-scoped incident list and evidence/RCA investigation tabs.
- `src/app/connections/page.tsx` — Current synthetic connection and notification-channel status.
- `src/services/demoApi.ts` — API helpers for tenants, summary, and attack generation.
- `src/services/phase3Api.ts` — Phase 3 onboarding, connection, and incident API with mock fixtures.
- `src/hooks/useAlertStream.ts` — WebSocket hook for live heartbeat streaming.
- `frontend/.env` — API base URL and optional mock-mode configuration.

## Available UI Controls

- Tenant dropdown: choose which tenant to simulate.
- Scenario dropdown: choose one of the demo attack scenarios.
- Dispatch button: send a POST request to `/demo/generate/attack`.
- Heartbeat feed: live JSON events received from `/ws/heartbeat`.
- Demo response panel: shows the last backend accept response.

## API Contracts

### `GET /tenants`

Returns a list of tenants:

- `id`
- `name`
- `live_alert_count`
- `health`

### `GET /stats/summary`

Returns summary data for the dashboard:

- `model_confidence`
- `critical_alerts`

### `POST /demo/generate/attack`

Request body:

```json
{
  "tenant_id": "google",
  "scenario": "credential_theft"
}
```

Response body:

```json
{
  "status": "accepted",
  "tenant_id": "google",
  "scenario": "credential_theft",
  "heartbeat": {
    "type": "stage_heartbeat",
    "stage": "encoding",
    "entity_id": "vol-0a12",
    "ts": "2026-07-28T00:00:00Z"
  }
}
```

### WebSocket: `ws://127.0.0.1:8001/ws/heartbeat`

The frontend hook connects to this stream and receives periodic stage heartbeat messages.

## Local Run Instructions

1. From the `Capstone_final` project root, start the backend demo API. Its relative escalation-rule path requires this working directory:

```bash
python -m uvicorn backend.api_demo_ext.app:app --host 127.0.0.1 --port 8001
```

2. In `frontend`, copy `.env.example` to `.env` and start the app:

```bash
npm install
npm run dev
```

3. Open the dashboard at the URL shown by Vite.

## Phase 3 Demo Routes

- `/onboarding` — resumable tenant setup; live monitoring requires explicit confirmation.
- `/connections` — current source mode, region, and configured demo channels.
- `/incidents` and `/incidents/:incidentId` — persisted tenant-scoped RCA cases, evidence, timeline, candidate causes, knowledge-base explanation, and recommended checks.

Set `VITE_MOCK_MODE=true` in `frontend/.env` to exercise both the confident-category and UNKNOWN explanation fixtures without the Phase 3 API. Mock onboarding progress is stored in browser local storage. In API mode, RCA records are stored through the Phase 3 session factory; `CAPSTONE_DATABASE_URL` selects the database, defaulting to the local SQLite demo database.

## Troubleshooting

- If the frontend fails to connect, verify `frontend/.env` points to the backend base URL and `VITE_MOCK_MODE` is set as intended.
- If the WebSocket does not connect, confirm the backend app is running and reachable at `http://127.0.0.1:8001`.
- If the demo page shows no tenants, make sure the backend `/tenants` route returns JSON and the API is available.
