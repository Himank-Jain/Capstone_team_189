# Project Directory Structure Guide

The CAPSTONE-189 final delivery should preserve the existing backend package layout while adding the presentation and demo layers below.

## Required Layout
- frontend/ for the dashboard application shell.
- backend/api_demo_ext/ for demo-only API wrappers, auth, tenants, analytics, and websocket heartbeat transport.
- demo-generator/ for live event generation and scenario playbooks.
- docs/guides/ for implementation, directory structure, and testing guidance.

## Rules
- Do not mutate shared/types.py or shared/constants.py for transport-only additions.
- Keep demo controls tenant-scoped and additive to the backend.
- Ensure README and tests describe the expected scaffold.
