"""
phase2/alerting/notifiers/email_notifier.py
==========================================
P2-M14  Explainable Alert API — EmailNotifier
CAPSTONE-189

Sends an HTML email with an alert-details table via SMTP.

Design notes
------------
1. smtplib is synchronous/blocking; there is no stdlib async SMTP
   client. Rather than pull in a whole extra dependency (aiosmtplib)
   just for this one channel, _send() runs the blocking smtplib call
   via `asyncio.to_thread` so it doesn't stall the event loop that
   NotificationDispatcher's asyncio.gather() is also using for the
   Slack/PagerDuty channels running concurrently.

2. SMTP client injection (DIP). Accepts an `smtp_client_factory`
   callable — `() -> smtplib.SMTP`-compatible context manager — rather
   than constructing smtplib.SMTP(host, port) internally, so tests can
   inject a fake/mock factory with no real network or credentials.
   Defaults to a real smtplib.SMTP/SMTP_SSL factory built from the
   host/port/use_tls constructor args if none is supplied.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Callable, List, Optional

from ..api.models import AlertPayloadModel
from .base_notifier import BaseNotifier


def _default_smtp_client_factory(
    smtp_host: str, smtp_port: int, use_tls: bool, username: Optional[str], password: Optional[str]
) -> Callable[[], smtplib.SMTP]:
    def _factory() -> smtplib.SMTP:
        client = (
            smtplib.SMTP_SSL(smtp_host, smtp_port)
            if use_tls
            else smtplib.SMTP(smtp_host, smtp_port)
        )
        if username and password:
            client.login(username, password)
        return client

    return _factory


class EmailNotifier(BaseNotifier):
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        from_addr: str,
        to_addrs: List[str],
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = True,
        smtp_client_factory: Optional[Callable[[], smtplib.SMTP]] = None,
    ) -> None:
        """
        Parameters
        ----------
        smtp_client_factory:
            Zero-arg callable returning an open, ready-to-send
            smtplib.SMTP-compatible object (context-manager protocol
            supported). Injected for testability — see design note 2.
            Defaults to a real SMTP_SSL/SMTP client built from the
            other constructor args.
        """
        super().__init__(channel_name="email")
        self._from_addr = from_addr
        self._to_addrs = to_addrs
        self._smtp_client_factory = smtp_client_factory or _default_smtp_client_factory(
            smtp_host, smtp_port, use_tls, username, password
        )

    def _build_html_body(self, payload: AlertPayloadModel) -> str:
        rows = "".join(
            f"<tr><td style='padding:4px 12px;border:1px solid #ddd;'><b>{label}</b></td>"
            f"<td style='padding:4px 12px;border:1px solid #ddd;'>{value}</td></tr>"
            for label, value in [
                ("Entity", payload.entity_id),
                ("Timestamp", payload.batch_ts.isoformat()),
                ("Final score", f"{payload.final_score:.3f}"),
                ("Severity", payload.severity.value),
                ("Escalation level", payload.sev_level.value),
                ("Deviation score", f"{payload.deviation_score:.3f}"),
                ("Drift score", f"{payload.drift_score:.3f}"),
                ("Similarity score", f"{payload.similarity_score:.3f}"),
                ("Group type", payload.group_type.value),
                ("Related incidents", ", ".join(payload.related_ids) or "none"),
                ("Target team", payload.target_team),
                ("Cloud / region", f"{payload.cloud_provider} / {payload.region}"),
                ("Contributing features", ", ".join(payload.contributing_features) or "n/a"),
            ]
        )
        return (
            "<html><body>"
            f"<h2>{payload.severity.value} anomaly — {payload.entity_id}</h2>"
            f"<table style='border-collapse:collapse;'>{rows}</table>"
            "</body></html>"
        )

    def _send_blocking(self, payload: AlertPayloadModel) -> str:
        message = MIMEMultipart("alternative")
        message["Subject"] = f"[{payload.severity.value}] Anomaly alert — {payload.entity_id}"
        message["From"] = self._from_addr
        message["To"] = ", ".join(self._to_addrs)
        message.attach(MIMEText(self._build_html_body(payload), "html"))

        client = self._smtp_client_factory()
        try:
            client.sendmail(self._from_addr, self._to_addrs, message.as_string())
        finally:
            quit_fn = getattr(client, "quit", None) or getattr(client, "close", None)
            if quit_fn is not None:
                quit_fn()
        return f"sent to {len(self._to_addrs)} recipient(s)"

    async def _send(self, payload: AlertPayloadModel) -> str:
        return await asyncio.to_thread(self._send_blocking, payload)
