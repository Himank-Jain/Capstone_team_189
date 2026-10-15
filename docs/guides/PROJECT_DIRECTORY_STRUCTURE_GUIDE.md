# Project Directory Structure Guide

The CAPSTONE-189 final delivery keeps application routes in the Phase 3 package and adds the presentation layer below.

## Required Layout
- frontend/ for the dashboard application shell.
- phase3/api/ for the FastAPI application, domain routers, authentication, tenants, analytics, and websocket transport.
- demo_generator/ for live event generation and scenario playbooks.
- docs/guides/ for implementation, directory structure, and testing guidance.

## Rules
- Do not mutate shared/types.py or shared/constants.py for transport-only additions.
- Keep demo controls tenant-scoped and additive to the backend.
- Ensure README and tests describe the expected scaffold.
