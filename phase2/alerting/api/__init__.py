"""
phase2/alerting/api
==========================================
P2-M14  Explainable Alert API
CAPSTONE-189

Terminal alert-delivery module. See alert_api.py for the FastAPI app
and module-level design notes.
"""

from .alert_api import create_app
from .dispatcher import NotificationDispatcher
from .models import AlertDispatchResponse, AlertPayloadModel, DispatchOutcome, EpisodeSummary
from .payload_builder import build_alert_payload
from .recent_alerts_store import RecentAlertsStore
from .websocket_manager import ConnectionManager

__all__ = [
    "create_app",
    "NotificationDispatcher",
    "AlertPayloadModel",
    "EpisodeSummary",
    "DispatchOutcome",
    "AlertDispatchResponse",
    "build_alert_payload",
    "RecentAlertsStore",
    "ConnectionManager",
]
