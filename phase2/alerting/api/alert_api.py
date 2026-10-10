"""
phase2/alerting/api/alert_api.py
==========================================
P2-M14  Explainable Alert API — FastAPI app
CAPSTONE-189

Terminal module of the pipeline: consumes AlertPayload from every
upstream module (P2-M9/M10/M12/M13) and dispatches it to Slack, Email,
PagerDuty, a dashboard time-series store, and a live WebSocket feed.

Design notes — deviations from the literal ticket text, and why
------------------------------------------------------------------
1. Standalone-runnable, dependency-free by default (ticket: "Build the
   FastAPI server so it can be run standalone (for testing) by
   accepting AlertPayload JSON directly"). create_app() defaults every
   optional dependency (notifiers list, dashboard store, recent-alerts
   Redis client) to something requiring NO external service: zero
   notifiers configured (dispatch simply returns an empty
   dispatch_status dict, not an error), InMemoryDashboardStore, and an
   in-memory RecentAlertsStore. Wiring real Slack/Email/PagerDuty/
   Postgres/Redis in is the CALLER's job (e.g. a
   scripts/run_alert_api.py reading env vars) via create_app(...)
   kwargs — this module itself never reads os.environ, keeping it
   trivially unit-testable with FastAPI's TestClient.

2. Notifier channel selection. AlertPayloadModel.notify_method is a
   SINGLE NotifyMethod (PAGE/SLACK/EMAIL) per the frozen shared/types.py
   contract — EscalationEngine already decided the ONE primary channel
   for this severity. Rather than only ever hitting that one channel
   and defeating the point of having multiple configured notifiers,
   POST /alert dispatches to ALL configured notifiers whose
   channel_name is either "dashboard" (always-on system-of-record,
   not a paging channel) or matches payload.notify_method's mapped
   channel — see _select_notifiers(). This keeps EscalationEngine's
   routing decision meaningful (a SLACK-tier alert never silently pages
   someone) while still writing every alert to the dashboard.

3. WebSocket broadcast happens AFTER dispatch+persist, not before —
   dashboard viewers should never see an alert flash by that then fails
   to appear in GET /alerts/recent moments later because persistence
   raced the broadcast.

4. GET /alert (singular, POST) accepts either an AlertPayloadModel
   JSON body directly OR is called by an orchestrator that already
   built one via payload_builder.build_alert_payload() — this endpoint
   itself has no opinion on how the payload was constructed, matching
   the ticket's "accepts AlertPayload and dispatches it" framing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from shared.types import NotifyMethod

from ..notifiers.base_notifier import BaseNotifier
from ..notifiers.dashboard_writer import DashboardWriter, InMemoryDashboardStore
from .dispatcher import NotificationDispatcher
from .models import AlertDispatchResponse, AlertPayloadModel, DispatchOutcome
from .recent_alerts_store import RecentAlertsStore
from .websocket_manager import ConnectionManager

logger_obj: logging.Logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"

# NotifyMethod -> the notifier channel_name(s) that method is allowed to
# reach, beyond the always-on "dashboard" channel. See design note 2.
_NOTIFY_METHOD_CHANNELS = {
    NotifyMethod.PAGE: {"pagerduty", "slack"},
    NotifyMethod.SLACK: {"slack"},
    NotifyMethod.EMAIL: {"email"},
}


def _select_notifiers(all_notifiers: List[BaseNotifier], notify_method: NotifyMethod) -> List[BaseNotifier]:
    allowed = _NOTIFY_METHOD_CHANNELS.get(notify_method, set()) | {"dashboard"}
    return [n for n in all_notifiers if n.channel_name in allowed]


def create_app(
    notifiers: Optional[List[BaseNotifier]] = None,
    recent_alerts_store: Optional[RecentAlertsStore] = None,
    connection_manager: Optional[ConnectionManager] = None,
    notification_dispatcher: Optional[object] = None,
) -> FastAPI:
    """
    Build the FastAPI app. See module docstring, design note 1, for why
    every argument defaults to a dependency-free implementation.

    Parameters
    ----------
    notifiers:
        List of configured BaseNotifier instances (SlackNotifier,
        EmailNotifier, PagerDutyNotifier, DashboardWriter, ...).
        Defaults to a single DashboardWriter(InMemoryDashboardStore())
        so the dashboard/recent-alerts flow works even with zero
        external channels configured.
    recent_alerts_store:
        Defaults to an in-memory RecentAlertsStore (no Redis required).
    connection_manager:
        Defaults to a fresh ConnectionManager.
    """
    app = FastAPI(title="Explainable Alert API", version="1.0.0")

    app.state.notifiers = notifiers if notifiers is not None else [DashboardWriter(InMemoryDashboardStore())]
    app.state.dispatcher = NotificationDispatcher(app.state.notifiers)
    app.state.notification_dispatcher = notification_dispatcher
    app.state.tenant_policy_lookup = getattr(notification_dispatcher, "resolve_policy_for_alert", None)
    app.state.recent_alerts_store = recent_alerts_store if recent_alerts_store is not None else RecentAlertsStore()
    app.state.connection_manager = connection_manager if connection_manager is not None else ConnectionManager()

    @app.post("/alert", response_model=AlertDispatchResponse)
    async def post_alert(payload: AlertPayloadModel) -> AlertDispatchResponse:
        selected = _select_notifiers(app.state.notifiers, payload.notify_method)
        dispatcher = NotificationDispatcher(selected) if selected != app.state.notifiers else app.state.dispatcher

        if app.state.notification_dispatcher is not None:
            from phase3.shared.types import NotificationPolicy

            tenant_id = getattr(payload, "tenant_id", None)
            if app.state.tenant_policy_lookup is not None:
                policy = await app.state.tenant_policy_lookup(payload, tenant_id=tenant_id)
            else:
                policy = NotificationPolicy(
                    tenant_id=tenant_id or "default",
                    allowed_channels=[payload.notify_method.value.lower()],
                )
            results = await app.state.notification_dispatcher.dispatch(payload, policy)
            dispatch_status = {
                result.channel: DispatchOutcome(
                    channel=result.channel,
                    success=result.success,
                    detail=result.detail or result.error or "",
                    latency_ms=None,
                )
                for result in results
            }
        else:
            dispatch_status = await dispatcher.dispatch(payload)

        try:
            await app.state.recent_alerts_store.add(payload)
        except Exception as exc:  # noqa: BLE001 -- persistence failure must not fail the response
            logger_obj.error("[alert_api] failed to persist alert to RecentAlertsStore: %s", exc)

        try:
            await app.state.connection_manager.broadcast(payload.model_dump_json())
        except Exception as exc:  # noqa: BLE001 -- see websocket_manager's own per-connection isolation
            logger_obj.error("[alert_api] failed to broadcast alert over WebSocket: %s", exc)

        all_succeeded = all(outcome.success for outcome in dispatch_status.values())
        return AlertDispatchResponse(
            alert_id=payload.alert_id,
            entity_id=payload.entity_id,
            dispatch_status=dispatch_status,
            all_succeeded=all_succeeded,
        )

    @app.get("/alerts/recent")
    async def get_recent_alerts(limit: int = 100):
        if limit < 1 or limit > 1000:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
        return await app.state.recent_alerts_store.get_recent(n=limit)

    @app.websocket("/alerts/stream")
    async def alerts_stream(websocket: WebSocket) -> None:
        await app.state.connection_manager.connect(websocket)
        try:
            while True:
                # Dashboard clients don't send anything meaningful; this
                # just keeps the connection open and detects disconnects.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            app.state.connection_manager.disconnect(websocket)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_page() -> str:
        index_path = _STATIC_DIR / "index.html"
        return index_path.read_text(encoding="utf-8")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {
            "status": "ok",
            "notifiers": [n.channel_name for n in app.state.notifiers],
            "websocket_connections": app.state.connection_manager.n_connections,
        }

    return app


# Default app instance for `uvicorn phase2.alerting.api.alert_api:app` — runs
# standalone with zero external dependencies per design note 1. A real
# deployment should instead call create_app(notifiers=[...]) itself (e.g.
# from a small scripts/run_alert_api.py that reads env vars/config.yaml
# and passes real SlackNotifier/EmailNotifier/PagerDutyNotifier/
# PostgresDashboardStore instances in).
app = create_app()
