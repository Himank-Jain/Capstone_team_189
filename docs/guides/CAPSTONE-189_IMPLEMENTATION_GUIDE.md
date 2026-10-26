# CAPSTONE-189 Implementation Guide

This guide captures the additive frontend/demo layer requested for the SOC dashboard and live demonstration environment.

## Scope
- Preserve the frozen backend contracts in shared/types.py and shared/constants.py.
- Build new surface area only in frontend/, phase3/api/, and demo_generator/.
- Keep all new routes and demo helpers isolated from the Phase 1/Phase 2 modules.

## Delivery Goals
1. Provide a Vite + TypeScript dashboard shell with routes for login, tenant selection, overview, alert feed, explainability, analytics, settings, and demo controls.
2. Add a demo API wrapper layer for auth, tenants, analytics, and demo generator controls.
3. Add a Python-based demo generator service and scenario playbooks.
4. Provide a verification checklist and a README that links to this guide.
