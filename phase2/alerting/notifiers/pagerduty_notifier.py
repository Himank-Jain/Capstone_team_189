"""
phase2/alerting/notifiers/pagerduty_notifier.py
==========================================
P2-M14  Explainable Alert API — PagerDutyNotifier
CAPSTONE-189

POSTs a trigger event to PagerDuty's Events API v2
(https://events.pagerduty.com/v2/enqueue).

Design notes
------------
1. Severity mapping. PagerDuty Events API v2 only accepts
   {"critical", "error", "warning", "info"} for `payload.severity` --
   NOT this project's own Severity enum values. Mapped explicitly
   rather than lower-casing (HIGH would otherwise become the
   nonexistent "high").

2. dedup_key = entity_id, not alert_id. Using a fresh alert_id (UUID4
   per alert) as PagerDuty's dedup_key would defeat PagerDuty's own
   server-side alert grouping entirely -- every alert would open a new
   incident even for the same entity. entity_id is what should
   correlate repeat firings into the same PagerDuty incident, so the
   dedup_key here is `pd:{entity_id}` (P2-M11's own AlertDeduplicator
   already keeps a SEPARATE, upstream layer of dedup; this is a second,
   PagerDuty-native safety net, not a replacement for it).

3. Only PAGE-worthy alerts reach here in practice (this module doesn't
   itself check payload.notify_method -- see NotificationDispatcher's
   channel-selection logic in dispatcher.py / alert_api.py, which is
   where that filtering decision belongs, not inside an individual
   notifier).
"""

from __future__ import annotations

from typing import Any

from ..api.models import AlertPayloadModel
from .base_notifier import BaseNotifier

_PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"

_SEVERITY_MAP = {
    "CRITICAL": "critical",
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "info",
}


class PagerDutyNotifier(BaseNotifier):
    def __init__(
        self, routing_key: str, http_client: Any, events_url: str = _PAGERDUTY_EVENTS_URL
    ) -> None:
        """
        Parameters
        ----------
        routing_key:
            PagerDuty Events API v2 integration routing key.
        http_client:
            Injected async HTTP client (e.g. httpx.AsyncClient()) — same
            DIP pattern as SlackNotifier.
        """
        super().__init__(channel_name="pagerduty")
        self._routing_key = routing_key
        self._http_client = http_client
        self._events_url = events_url

    def _build_event(self, payload: AlertPayloadModel) -> dict:
        return {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "dedup_key": f"pd:{payload.entity_id}",
            "payload": {
                "summary": (
                    f"{payload.severity.value} anomaly on {payload.entity_id} "
                    f"(score={payload.final_score:.3f})"
                ),
                "source": payload.entity_id,
                "severity": _SEVERITY_MAP.get(payload.severity.value, "warning"),
                "timestamp": payload.batch_ts.isoformat(),
                "component": payload.target_team,
                "group": payload.group_type.value,
                "class": "behavioral_anomaly",
                "custom_details": {
                    "final_score": payload.final_score,
                    "deviation_score": payload.deviation_score,
                    "drift_score": payload.drift_score,
                    "similarity_score": payload.similarity_score,
                    "sev_level": payload.sev_level.value,
                    "cloud_provider": payload.cloud_provider,
                    "region": payload.region,
                    "related_ids": payload.related_ids,
                    "contributing_features": payload.contributing_features,
                },
            },
        }

    async def _send(self, payload: AlertPayloadModel) -> str:
        event = self._build_event(payload)
        response = await self._http_client.post(self._events_url, json=event)
        status_code = getattr(response, "status_code", None)
        if status_code is not None and status_code >= 300:
            raise RuntimeError(
                f"PagerDuty Events API returned HTTP {status_code}: {getattr(response, 'text', '')}"
            )
        return f"HTTP {status_code}" if status_code is not None else "sent"
