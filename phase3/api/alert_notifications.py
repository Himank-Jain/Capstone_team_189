"""Outbound alert notifications for the demo API.

Every channel reports what actually happened. A channel without credentials
returns ``not_configured``; it is never reported as sent. Configuration comes
from environment variables (see ``docs/guides/AUTH_NOTIFICATIONS_EXPLANATION_CHANGES.md``):

* EMAIL      SMTP settings saved for the workspace on the Settings page
             (password encrypted at rest), otherwise environment variables:
             DEMO_EMAIL_SENDER + DEMO_EMAIL_PASSWORD, optional SMTP_HOST,
             SMTP_PORT, SMTP_SECURITY, SMTP_USERNAME (Gmail by default).
             Recipients: the workspace's saved recipient list, otherwise
             DEMO_EMAIL_RECIPIENT, otherwise every registered member of the
             workspace, otherwise DEMO_EMAIL_DEFAULT_RECIPIENT.
* SLACK      SLACK_WEBHOOK_URL (Slack incoming webhook).
* WEBHOOK    ALERT_WEBHOOK_URL (+ optional ALERT_WEBHOOK_SECRET for an
             HMAC-SHA256 ``X-Capstone-Signature`` header).
* PAGERDUTY  PAGERDUTY_ROUTING_KEY (Events API v2).
* PAGE       Always available: the alert is pushed to signed-in dashboards.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import base64

import httpx
from cryptography.fernet import Fernet, InvalidToken

from phase3.db.models import TenantMembershipRow, TenantRow, UserRow

from .email_service import SMTP_SECURITY_MODES, EmailService, SmtpSettings

_EMAIL_SETTINGS_KEY = "email_smtp"


def _platform():
    # Imported lazily: the routers package imports this module at load time.
    from .routers import _support

    return _support

SUPPORTED_CHANNELS = ("PAGE", "EMAIL", "SLACK", "WEBHOOK", "PAGERDUTY")
_SEVERITY_EMOJI = {"CRITICAL": ":red_circle:", "HIGH": ":large_orange_circle:", "MEDIUM": ":large_yellow_circle:", "LOW": ":large_green_circle:"}
_PAGERDUTY_SEVERITY = {"CRITICAL": "critical", "HIGH": "error", "MEDIUM": "warning", "LOW": "info"}
_EMAIL_LOG_DIR = Path(__file__).parent / "email_logs"

# Tests replace this to capture outbound HTTP without touching the network.
http_client_factory: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=10.0)


def dashboard_url() -> str:
    return os.getenv("CAPSTONE_DASHBOARD_URL", "http://127.0.0.1:5173").rstrip("/")


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


# ---------------------------------------------------------------------------
# Workspace email settings (saved from the Settings page)
# ---------------------------------------------------------------------------


def _fernet() -> Fernet:
    """Encryption for stored SMTP passwords.

    PLATFORM_CREDENTIAL_KEY if set, otherwise derived from the JWT signing
    secret. Changing either makes saved passwords unreadable (re-enter them).
    """
    secret = os.getenv("PLATFORM_CREDENTIAL_KEY", "").strip()
    if len(secret.encode("utf-8")) < 32:
        secret = "smtp-credentials:" + _platform()._resolve_jwt_secret()
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _read_tenant_settings(tenant_id: str) -> Dict[str, Any]:
    with _platform().platform_session_factory.session_scope() as session:
        row = session.get(TenantRow, tenant_id)
        state = dict((row.onboarding_state or {}) if row is not None else {})
    return dict(state.get("settings") or {})


def load_workspace_email_settings(tenant_id: str) -> Optional[Dict[str, Any]]:
    stored = _read_tenant_settings(tenant_id).get(_EMAIL_SETTINGS_KEY)
    return dict(stored) if isinstance(stored, dict) else None


def save_workspace_email_settings(
    tenant_id: str,
    *,
    host: str,
    port: int,
    security: str,
    username: str,
    password: Optional[str],
    sender: str,
    recipients: List[str],
) -> Dict[str, Any]:
    """Store SMTP settings for one workspace. A blank password keeps the saved one."""
    if security not in SMTP_SECURITY_MODES:
        raise ValueError(f"security must be one of {', '.join(SMTP_SECURITY_MODES)}")
    existing = load_workspace_email_settings(tenant_id) or {}
    if password:
        ciphertext = _fernet().encrypt("".join(password.split()).encode("utf-8")).decode("utf-8")
    elif existing.get("password_ciphertext"):
        ciphertext = existing["password_ciphertext"]
    else:
        raise ValueError("Enter the SMTP password (or app password)")
    record = {
        "host": host.strip(),
        "port": int(port),
        "security": security,
        "username": username.strip(),
        "sender": sender.strip(),
        "recipients": [item.strip() for item in recipients if item.strip()],
        "password_ciphertext": ciphertext,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _platform().ensure_demo_tenants()
    with _platform().platform_session_factory.session_scope() as session:
        row = session.get(TenantRow, tenant_id)
        if row is None:
            raise ValueError("Workspace not found")
        state = dict(row.onboarding_state or {})
        settings = dict(state.get("settings") or {})
        settings[_EMAIL_SETTINGS_KEY] = record
        state["settings"] = settings
        row.onboarding_state = state  # reassign so SQLAlchemy persists the JSON change
    return record


def clear_workspace_email_settings(tenant_id: str) -> None:
    with _platform().platform_session_factory.session_scope() as session:
        row = session.get(TenantRow, tenant_id)
        if row is None or not row.onboarding_state:
            return
        state = dict(row.onboarding_state)
        settings = dict(state.get("settings") or {})
        settings.pop(_EMAIL_SETTINGS_KEY, None)
        state["settings"] = settings
        row.onboarding_state = state


def resolve_smtp_settings(tenant_id: str) -> tuple[SmtpSettings, Optional[str]]:
    """The SMTP account to use, plus a problem description if it is unusable."""
    stored = load_workspace_email_settings(tenant_id)
    if stored:
        try:
            password = _fernet().decrypt(str(stored.get("password_ciphertext", "")).encode("utf-8")).decode("utf-8")
            problem = None
        except (InvalidToken, ValueError):
            password = ""
            problem = "The saved email password can no longer be decrypted (the server secret changed); re-enter it in Settings"
        return (
            SmtpSettings(
                host=str(stored.get("host", "")),
                port=int(stored.get("port") or 587),
                security=str(stored.get("security") or "starttls"),
                username=str(stored.get("username", "")),
                password=password,
                sender=str(stored.get("sender", "")),
                source="workspace",
            ),
            problem,
        )
    settings = SmtpSettings.from_env()
    if not settings.configured:
        return settings, "Email is not set up: add an SMTP account in Settings (or set DEMO_EMAIL_SENDER and DEMO_EMAIL_PASSWORD)"
    return settings, None


def resolve_email_recipients(tenant_id: str) -> List[str]:
    saved = (load_workspace_email_settings(tenant_id) or {}).get("recipients") or []
    if saved:
        return list(saved)
    override = _env("DEMO_EMAIL_RECIPIENT")
    if override:
        return [item.strip() for item in override.split(",") if item.strip()]
    _support = _platform()
    with _support.platform_session_factory.session_scope() as session:
        rows = (
            session.query(UserRow.email)
            .join(TenantMembershipRow, TenantMembershipRow.user_id == UserRow.user_id)
            .filter(
                TenantMembershipRow.tenant_id == tenant_id,
                UserRow.user_id != _support.LEGACY_DEMO_USER_ID,
            )
            .order_by(UserRow.email)
            .all()
        )
    members = [email for (email,) in rows if email]
    if members:
        return members
    fallback = _env("DEMO_EMAIL_DEFAULT_RECIPIENT")
    return [fallback] if fallback else []


def email_settings_summary(tenant_id: str) -> Dict[str, Any]:
    """Safe description of the email setup (never includes the password)."""
    settings, problem = resolve_smtp_settings(tenant_id)
    stored = load_workspace_email_settings(tenant_id) or {}
    return {
        "source": settings.source if (settings.configured or stored) else "none",
        "host": settings.host,
        "port": settings.port,
        "security": settings.security,
        "username": settings.username,
        "sender": settings.sender,
        "password_set": bool(settings.password) or bool(stored.get("password_ciphertext")),
        "recipients": list(stored.get("recipients") or []),
        "effective_recipients": resolve_email_recipients(tenant_id),
        "ready": settings.configured and problem is None,
        "problem": problem,
        "updated_at": stored.get("updated_at"),
    }


def channel_statuses(tenant_id: str) -> List[Dict[str, str]]:
    """Readiness of each channel for this tenant, without sending anything."""
    recipients = resolve_email_recipients(tenant_id)
    smtp, problem = resolve_smtp_settings(tenant_id)
    if problem or not smtp.configured:
        email = ("credentials_required", problem or "Add an SMTP account in Settings")
    elif not recipients:
        email = ("credentials_required", "No recipients: add members or a recipient list")
    else:
        where = "workspace settings" if smtp.source == "workspace" else "server environment"
        email = ("ready", f"{smtp.host} as {smtp.sender} to {len(recipients)} recipient(s) ({where})")
    webhook_ready = bool(_env("ALERT_WEBHOOK_URL"))
    return [
        {"channel": "PAGE", "status": "ready", "detail": "In-dashboard notifications for signed-in members"},
        {"channel": "EMAIL", "status": email[0], "detail": email[1]},
        {
            "channel": "SLACK",
            "status": "ready" if _env("SLACK_WEBHOOK_URL") else "credentials_required",
            "detail": "Slack incoming webhook" if _env("SLACK_WEBHOOK_URL") else "Set SLACK_WEBHOOK_URL",
        },
        {
            "channel": "SMS",
            "status": "credentials_required",
            "detail": "No SMS provider is wired into this build",
        },
        {
            "channel": "WEBHOOK",
            "status": "ready" if webhook_ready else "credentials_required",
            "detail": (
                "Signed JSON POST" if webhook_ready and _env("ALERT_WEBHOOK_SECRET")
                else "Unsigned JSON POST (set ALERT_WEBHOOK_SECRET to sign)" if webhook_ready
                else "Set ALERT_WEBHOOK_URL (and ALERT_WEBHOOK_SECRET)"
            ),
        },
        {
            "channel": "PAGERDUTY",
            "status": "ready" if _env("PAGERDUTY_ROUTING_KEY") else "credentials_required",
            "detail": "PagerDuty Events API v2" if _env("PAGERDUTY_ROUTING_KEY") else "Set PAGERDUTY_ROUTING_KEY",
        },
    ]


def _result(channel: str, status: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {
        "notify_method": channel,
        "channel": channel,
        "status": status,
        "sent": status in {"sent", "displayed"},
        "success": status in {"sent", "displayed"},
        "message": message,
        "detail": message,
        **extra,
    }


def _incident_link(payload: Dict[str, Any]) -> str:
    return f"{dashboard_url()}/incidents/{payload.get('alert_id', '')}"


def _summary(payload: Dict[str, Any]) -> str:
    score = float(payload.get("final_score") or 0.0)
    return (
        f"{payload.get('severity', 'UNKNOWN')} anomaly on {payload.get('entity_id', 'unknown')} "
        f"({payload.get('cloud_provider', '?')} {payload.get('region', '?')}), score {score:.2f}"
    )


def _log_email_failure(recipients: List[str], payload: Dict[str, Any], error: str) -> str:
    _EMAIL_LOG_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    log_file = _EMAIL_LOG_DIR / f"email_{now.strftime('%Y%m%d_%H%M%S_%f')}.json"
    log_file.write_text(
        json.dumps(
            {
                "timestamp": now.isoformat(),
                "to": recipients,
                "alert_id": payload.get("alert_id"),
                "severity": payload.get("severity"),
                "entity_id": payload.get("entity_id"),
                "error": error,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return str(log_file)


async def _send_email(
    payload: Dict[str, Any],
    tenant_id: str,
    subject: Optional[str],
    recipients: Optional[List[str]] = None,
) -> Dict[str, Any]:
    recipients = recipients if recipients is not None else resolve_email_recipients(tenant_id)
    email_to = ", ".join(recipients)
    if not recipients:
        return _result("EMAIL", "not_configured", "No email recipients for this workspace", email_to="")
    smtp, problem = resolve_smtp_settings(tenant_id)
    if problem or not smtp.configured:
        return _result(
            "EMAIL",
            "not_configured",
            problem or "Email is not set up: add an SMTP account in Settings",
            email_to=email_to,
        )
    outcome = await EmailService.send_alert_email_result(
        email_to, payload, subject_override=subject, settings=smtp
    )
    if outcome.get("sent"):
        return _result("EMAIL", "sent", f"Email sent to {email_to}", email_to=email_to)
    error = str(outcome.get("error") or "unknown error")
    return _result(
        "EMAIL",
        "failed",
        f"Email delivery failed: {error}",
        email_to=email_to,
        log_path=_log_email_failure(recipients, payload, error),
    )


async def _post(url: str, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> None:
    async with http_client_factory() as client:
        response = await client.post(url, json=body, headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")


async def _send_slack(payload: Dict[str, Any]) -> Dict[str, Any]:
    url = _env("SLACK_WEBHOOK_URL")
    if not url:
        return _result("SLACK", "not_configured", "Slack is not configured: set SLACK_WEBHOOK_URL")
    emoji = _SEVERITY_EMOJI.get(str(payload.get("severity")), ":white_circle:")
    body = {
        "text": f"{emoji} {_summary(payload)}",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"{emoji} *{_summary(payload)}*"}},
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Team: {payload.get('target_team', 'unassigned')} · <{_incident_link(payload)}|Open investigation>"}
                ],
            },
        ],
    }
    try:
        await _post(url, body)
    except Exception as exc:  # network or HTTP failure is reported, not raised
        return _result("SLACK", "failed", f"Slack delivery failed: {exc}")
    return _result("SLACK", "sent", "Posted to the configured Slack webhook")


async def _send_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    url = _env("ALERT_WEBHOOK_URL")
    if not url:
        return _result("WEBHOOK", "not_configured", "Webhook is not configured: set ALERT_WEBHOOK_URL")
    body = json.loads(json.dumps(payload, default=str))
    headers = {}
    secret = _env("ALERT_WEBHOOK_SECRET")
    if secret:
        signature = hmac.new(
            secret.encode("utf-8"), json.dumps(body, sort_keys=True).encode("utf-8"), hashlib.sha256
        ).hexdigest()
        headers["X-Capstone-Signature"] = signature
    try:
        await _post(url, body, headers)
    except Exception as exc:
        return _result("WEBHOOK", "failed", f"Webhook delivery failed: {exc}")
    return _result("WEBHOOK", "sent", "Posted to the configured webhook")


async def _send_pagerduty(payload: Dict[str, Any]) -> Dict[str, Any]:
    routing_key = _env("PAGERDUTY_ROUTING_KEY")
    if not routing_key:
        return _result("PAGERDUTY", "not_configured", "PagerDuty is not configured: set PAGERDUTY_ROUTING_KEY")
    event = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": f"capstone:{payload.get('alert_id')}",
        "payload": {
            "summary": _summary(payload),
            "source": str(payload.get("entity_id", "unknown")),
            "severity": _PAGERDUTY_SEVERITY.get(str(payload.get("severity")), "warning"),
            "component": str(payload.get("target_team", "unassigned")),
            "custom_details": {"link": _incident_link(payload)},
        },
    }
    try:
        await _post("https://events.pagerduty.com/v2/enqueue", event)
    except Exception as exc:
        return _result("PAGERDUTY", "failed", f"PagerDuty delivery failed: {exc}")
    return _result("PAGERDUTY", "sent", "Event sent to PagerDuty")


async def send_alert_notification(
    channel: str,
    payload: Dict[str, Any],
    tenant_id: str,
    *,
    subject: Optional[str] = None,
    email_recipients: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Deliver one alert through one channel and report the real outcome."""
    channel = channel.upper()
    try:
        if channel == "PAGE":
            return _result("PAGE", "displayed", "Alert pushed to signed-in dashboards")
        if channel == "EMAIL":
            return await _send_email(payload, tenant_id, subject, email_recipients)
        if channel == "SLACK":
            return await _send_slack(payload)
        if channel == "WEBHOOK":
            return await _send_webhook(payload)
        if channel == "PAGERDUTY":
            return await _send_pagerduty(payload)
    except Exception as exc:  # defensive: a notifier bug must not break alert creation
        return _result(channel, "failed", f"Notification failed: {exc}")
    return _result(channel, "not_configured", f"Channel {channel} is not supported")


def build_test_payload(tenant_id: str, actor_email: str) -> Dict[str, Any]:
    entity_id, provider, region = "notification-test", "n/a", "n/a"
    connection = _platform().TENANT_CONNECTIONS.get(tenant_id)
    if connection:
        provider, region = connection
    return {
        "alert_id": f"test-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "severity": "LOW",
        "sev_level": "SEV4",
        "final_score": 0.0,
        "deviation_score": 0.0,
        "drift_score": 0.0,
        "similarity_score": 0.0,
        "cloud_provider": provider,
        "region": region,
        "target_team": f"test requested by {actor_email}",
        "batch_ts": datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "SUPPORTED_CHANNELS",
    "build_test_payload",
    "channel_statuses",
    "resolve_email_recipients",
    "send_alert_notification",
]
