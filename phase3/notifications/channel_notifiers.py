"""Phase 3 notification channel implementations for SMS, webhook, and PagerDuty."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional

from shared.types import AlertPayload, Severity

logger = logging.getLogger(__name__)


def _normalize_for_json(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_for_json(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_for_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_for_json(val) for key, val in value.items()}
    return value


class BaseNotifier(ABC):
    channel_name: str = "base"

    def __init__(self, channel_name: str, http_client: Optional[Any] = None) -> None:
        self.channel_name = channel_name
        self._http_client = http_client

    async def notify(self, payload: AlertPayload) -> Dict[str, Any]:
        try:
            detail = await self._send(payload)
            return {"channel": self.channel_name, "success": True, "detail": detail}
        except Exception as exc:  # pragma: no cover - defensive branch
            logger.warning("[%s] notification failed: %s", self.channel_name, exc)
            return {"channel": self.channel_name, "success": False, "detail": f"{type(exc).__name__}: {exc}"}

    @abstractmethod
    async def _send(self, payload: AlertPayload) -> str:
        raise NotImplementedError


class SmsNotifier(BaseNotifier):
    """SMS channel for time-gated, CRITICAL-only escalation messages."""

    def __init__(
        self,
        phone_number: str,
        http_client: Optional[Any] = None,
        *,
        allow_after_hours: bool = False,
        sms_url: str = "https://sms.internal.local/dispatch",
        now_provider: Optional[Callable[[], datetime]] = None,
    ) -> None:
        super().__init__("sms", http_client)
        self._phone_number = phone_number
        self._allow_after_hours = allow_after_hours
        self._sms_url = sms_url
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def _is_after_hours(self) -> bool:
        now = self._now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        else:
            now = now.astimezone(timezone.utc)
        hour = now.hour
        return hour < 7 or hour >= 19

    async def _send(self, payload: AlertPayload) -> str:
        if payload.severity != Severity.CRITICAL:
            raise ValueError("SMS notifications are CRITICAL-only")
        if self._is_after_hours() and not self._allow_after_hours:
            raise ValueError("SMS notifications are gated to business hours or explicit opt-in")

        message = {
            "to": self._phone_number,
            "channel": "sms",
            "entity_id": payload.entity_id,
            "severity": payload.severity.value,
            "score": payload.final_score,
            "target_team": payload.target_team,
            "summary": f"{payload.entity_id} reported a {payload.severity.value} anomaly.",
        }
        if self._http_client is not None:
            await self._http_client.post(self._sms_url, json=message)
        return "sms-dispatched"


class WebhookNotifier(BaseNotifier):
    """Webhook sender with HMAC-SHA256 signing for SIEM or downstream integration."""

    def __init__(self, url: str, secret: str, http_client: Optional[Any] = None) -> None:
        super().__init__("webhook", http_client)
        self._url = url
        self._secret = secret

    async def _send(self, payload: AlertPayload) -> str:
        body = _normalize_for_json(payload.__dict__)
        body_json = json.dumps(body, sort_keys=True)
        signature = hmac.new(self._secret.encode("utf-8"), body_json.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {"Content-Type": "application/json", "X-Capstone-Signature": signature}
        if self._http_client is not None:
            await self._http_client.post(self._url, json=body, headers=headers)
        return "webhook-dispatched"


class PagerDutyNotifier(BaseNotifier):
    """PagerDuty event sender using the Events API v2 format."""

    _SEVERITY_MAP = {
        "CRITICAL": "critical",
        "HIGH": "error",
        "MEDIUM": "warning",
        "LOW": "info",
    }

    def __init__(self, routing_key: str, http_client: Optional[Any] = None, events_url: str = "https://events.pagerduty.com/v2/enqueue") -> None:
        super().__init__("pagerduty", http_client)
        self._routing_key = routing_key
        self._events_url = events_url

    async def _send(self, payload: AlertPayload) -> str:
        event = {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "dedup_key": f"pd:{payload.entity_id}",
            "payload": {
                "summary": f"{payload.severity.value} anomaly on {payload.entity_id} (score={payload.final_score:.3f})",
                "source": payload.entity_id,
                "severity": self._SEVERITY_MAP.get(payload.severity.value, "warning"),
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
                },
            },
        }
        if self._http_client is not None:
            await self._http_client.post(self._events_url, json=event)
        return "pagerduty-dispatched"


__all__ = ["BaseNotifier", "SmsNotifier", "WebhookNotifier", "PagerDutyNotifier"]
