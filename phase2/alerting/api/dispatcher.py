"""
phase2/alerting/api/dispatcher.py
==========================================
P2-M14  Explainable Alert API — NotificationDispatcher
CAPSTONE-189

Fans one AlertPayloadModel out to every enabled BaseNotifier in
parallel via asyncio.gather(..., return_exceptions=True), per the
ticket's own "Alert delivery failures (Slack down, SMTP error) must not
block the pipeline" watch-out.

Design notes
------------
1. Belt-and-suspenders exception handling. Every BaseNotifier.notify()
   already never raises (it converts exceptions into a failed
   DispatchOutcome internally — see base_notifier.py). gather's
   return_exceptions=True is kept anyway as a second line of defense:
   if a future notifier implementation forgets that contract, one
   channel's bug still can't take down the whole dispatch call.

2. Channel selection stays OUTSIDE individual notifiers (base_notifier
   design note 3 / pagerduty_notifier design note 3). This dispatcher
   sends to every notifier it's given — the caller (alert_api.py's
   POST /alert handler) decides which notifiers are "enabled" for a
   given payload (e.g. skip PagerDuty for a SLACK-only notify_method).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List

from ..notifiers.base_notifier import BaseNotifier
from .models import AlertPayloadModel, DispatchOutcome

logger_obj: logging.Logger = logging.getLogger(__name__)


class NotificationDispatcher:
    def __init__(self, notifiers: List[BaseNotifier]) -> None:
        self._notifiers = notifiers

    async def dispatch(self, payload: AlertPayloadModel) -> Dict[str, DispatchOutcome]:
        """
        Send `payload` to every configured notifier concurrently.

        Returns
        -------
        Dict[str, DispatchOutcome]
            Keyed by channel_name. Always has one entry per configured
            notifier, regardless of individual success/failure.
        """
        if not self._notifiers:
            return {}

        results = await asyncio.gather(
            *(notifier.notify(payload) for notifier in self._notifiers),
            return_exceptions=True,
        )

        outcomes: Dict[str, DispatchOutcome] = {}
        for notifier, result in zip(self._notifiers, results):
            if isinstance(result, BaseException):
                logger_obj.error(
                    "[NotificationDispatcher] channel=%s raised despite "
                    "BaseNotifier.notify()'s no-raise contract -- %s: %s",
                    notifier.channel_name,
                    type(result).__name__,
                    result,
                )
                outcomes[notifier.channel_name] = DispatchOutcome(
                    channel=notifier.channel_name,
                    success=False,
                    detail=f"{type(result).__name__}: {result}",
                )
            else:
                outcomes[notifier.channel_name] = result
        return outcomes
