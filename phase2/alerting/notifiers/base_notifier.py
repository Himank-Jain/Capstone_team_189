"""
phase2/alerting/notifiers/base_notifier.py
==========================================
P2-M14  Explainable Alert API — BaseNotifier
CAPSTONE-189

Common abstraction every delivery channel (Slack/Email/PagerDuty/
future channels) implements, so NotificationDispatcher (dispatcher.py)
can fan an AlertPayloadModel out to all enabled channels uniformly via
asyncio.gather(..., return_exceptions=True) -- per the ticket's own
"Alert delivery failures must not block the pipeline" watch-out.

Each concrete notifier is responsible for catching its OWN
channel-specific exceptions (SlackNotifier catches httpx errors,
EmailNotifier catches smtplib errors, etc.) and returning a
DispatchOutcome(success=False, detail=...) rather than raising --
dispatcher.py's return_exceptions=True is a second line of defense for
anything a notifier fails to catch itself, not the primary mechanism.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from ..api.models import AlertPayloadModel, DispatchOutcome


class BaseNotifier(ABC):
    """
    Parameters
    ----------
    channel_name:
        Short identifier used as the dispatch_status dict key (e.g.
        "slack", "email", "pagerduty") and in DispatchOutcome.channel.
    """

    def __init__(self, channel_name: str) -> None:
        self.channel_name = channel_name

    @abstractmethod
    async def _send(self, payload: AlertPayloadModel) -> str:
        """
        Perform the actual delivery. Return a short human-readable
        success detail (e.g. an HTTP status or message id). Raise on
        failure -- notify() below converts the exception into a
        DispatchOutcome(success=False, ...) so the caller never has to
        catch anything itself.
        """
        raise NotImplementedError

    async def notify(self, payload: AlertPayloadModel) -> DispatchOutcome:
        """
        Timed wrapper around _send() that NEVER raises -- always
        returns a DispatchOutcome, success or failure. This is what
        NotificationDispatcher actually calls.
        """
        start = time.monotonic()
        try:
            detail = await self._send(payload)
            latency_ms = (time.monotonic() - start) * 1000.0
            return DispatchOutcome(
                channel=self.channel_name, success=True, detail=detail, latency_ms=latency_ms
            )
        except Exception as exc:  # noqa: BLE001 -- deliberate: no channel failure may propagate
            latency_ms = (time.monotonic() - start) * 1000.0
            return DispatchOutcome(
                channel=self.channel_name,
                success=False,
                detail=f"{type(exc).__name__}: {exc}",
                latency_ms=latency_ms,
            )
