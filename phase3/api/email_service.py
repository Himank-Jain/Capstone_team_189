"""Email notification service for demo alerts."""

import asyncio
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Dict, Optional

SMTP_SECURITY_MODES = ("starttls", "ssl", "none")
_DEFAULT_PORTS = {"starttls": 587, "ssl": 465, "none": 25}


@dataclass(frozen=True)
class SmtpSettings:
    """Where and how alert email is sent. ``password`` is never logged or returned."""

    host: str
    port: int
    security: str  # starttls | ssl | none
    username: str
    password: str
    sender: str
    source: str = "environment"  # environment | workspace

    @property
    def configured(self) -> bool:
        return bool(self.host and self.username and self.password and "@" in self.sender)

    @classmethod
    def from_env(cls) -> "SmtpSettings":
        security = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
        if security not in SMTP_SECURITY_MODES:
            security = "starttls"
        port_text = os.getenv("SMTP_PORT", "").strip()
        sender = EmailService.resolve_sender_email().strip()
        return cls(
            host=os.getenv("SMTP_HOST", "smtp.gmail.com").strip(),
            port=int(port_text) if port_text.isdigit() else _DEFAULT_PORTS[security],
            security=security,
            username=os.getenv("SMTP_USERNAME", "").strip() or sender,
            password=EmailService.resolve_sender_password(),
            sender=sender,
            source="environment",
        )

_TENANT_EMAIL_DEFAULTS = {
    "google": "ops@google-demo.internal",
    "microsoft": "security@microsoft-demo.internal",
    "amazon": "security@amazon-demo.internal",
    "oracle": "soc@oracle-demo.internal",
    "acme": "alerts@acme-demo.internal",
}


class EmailService:
    """Send email notifications for demo alerts."""

    # Gmail SMTP configuration
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587

    @staticmethod
    def resolve_sender_email() -> str:
        return os.getenv("DEMO_EMAIL_SENDER", "capstone.demo.alerts@gmail.com")

    @staticmethod
    def resolve_sender_password() -> str:
        raw = os.getenv("DEMO_EMAIL_PASSWORD", "")
        # Gmail app passwords are shown in 4-character groups. Remove all whitespace
        # so pasted values like "abcd efgh ijkl mnop" authenticate correctly.
        return "".join(raw.split())

    @staticmethod
    def resolve_recipient_email(tenant_id: Optional[str] = None) -> str:
        recipient = os.getenv("DEMO_EMAIL_RECIPIENT", "").strip()
        if recipient:
            return recipient

        candidate_tenant = (tenant_id or os.getenv("DEMO_TENANT_ID") or "").strip().lower()
        if candidate_tenant:
            default_recipient = _TENANT_EMAIL_DEFAULTS.get(candidate_tenant)
            if default_recipient:
                return default_recipient

        return os.getenv("DEMO_EMAIL_DEFAULT_RECIPIENT", "").strip()

    @staticmethod
    def is_configured() -> bool:
        sender_email = EmailService.resolve_sender_email().strip()
        sender_password = EmailService.resolve_sender_password().strip()
        return bool(sender_email and sender_password and "@" in sender_email)

    @staticmethod
    def build_alert_html(alert_data: Dict[str, Any], recipient: str) -> tuple[str, str]:
        """Build HTML and plain text email body for alert."""
        entity_id = alert_data.get("entity_id", "unknown")
        severity = alert_data.get("severity", "UNKNOWN")
        score = alert_data.get("final_score", 0.0)
        alert_id = alert_data.get("alert_id", "unknown")
        cloud_provider = alert_data.get("cloud_provider", "AWS")
        region = alert_data.get("region", "unknown")
        target_team = alert_data.get("target_team", "Security Team")
        dashboard_base = os.getenv("CAPSTONE_DASHBOARD_URL", "http://127.0.0.1:5173").rstrip("/")
        dashboard_link = f"{dashboard_base}/incidents/{alert_id}"

        # Severity color mapping
        severity_colors = {
            "CRITICAL": "#dc2626",
            "HIGH": "#f97316",
            "MEDIUM": "#eab308",
            "LOW": "#22c55e",
        }

        severity_color = severity_colors.get(severity, "#666666")

        # HTML body
        html = f"""
        <html>
            <head>
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                        color: #333;
                    }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{
                        background: #0b0f17;
                        color: white;
                        padding: 20px;
                        border-radius: 8px 8px 0 0;
                    }}
                    .header h1 {{ margin: 0; font-size: 24px; }}
                    .content {{
                        background: #f9fafb;
                        padding: 20px;
                        border-radius: 0 0 8px 8px;
                        border: 1px solid #e5e7eb;
                    }}
                    .alert-box {{
                        background: white;
                        padding: 16px;
                        border-radius: 8px;
                        margin: 12px 0;
                        border-left: 4px solid {severity_color};
                    }}
                    .metric {{ display: inline-block; margin: 8px 12px 8px 0; }}
                    .label {{ color: #6b7280; font-size: 12px; text-transform: uppercase; }}
                    .value {{ font-weight: bold; font-size: 16px; color: #111827; }}
                    .severity-badge {{
                        background: {severity_color};
                        color: white;
                        padding: 6px 12px;
                        border-radius: 6px;
                        font-weight: bold;
                        display: inline-block;
                    }}
                    .button {{
                        background: #2563eb;
                        color: white;
                        padding: 12px 24px;
                        border-radius: 8px;
                        text-decoration: none;
                        display: inline-block;
                        margin-top: 12px;
                    }}
                    .footer {{
                        color: #6b7280;
                        font-size: 12px;
                        margin-top: 20px;
                        text-align: center;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🚨 Security Alert Notification</h1>
                        <p style="margin: 8px 0 0 0; color: #d1d5db;">CAPSTONE-189 Demo System</p>
                    </div>
                    <div class="content">
                        <p>Hello Security Team,</p>
                        <p>A new security alert has been detected and requires your attention:</p>

                        <div class="alert-box">
                            <div
                                style="display: flex; justify-content: space-between;
                                align-items: center;
                                margin-bottom: 12px;"
                            >
                                <h2 style="margin: 0; font-size: 18px;">Alert Summary</h2>
                                <span class="severity-badge">{severity}</span>
                            </div>

                            <div style="border-top: 1px solid #e5e7eb; padding-top: 12px;">
                                <div class="metric">
                                    <div class="label">Alert ID</div>
                                    <div
                                        class="value"
                                        style="font-family: monospace; font-size: 12px;"
                                    >
                                        {alert_id}
                                    </div>
                                </div>
                                <div class="metric">
                                    <div class="label">Entity ID</div>
                                    <div class="value">{entity_id}</div>
                                </div>
                                <br/>
                                <div class="metric">
                                    <div class="label">Risk Score</div>
                                    <div class="value">{score:.2%}</div>
                                </div>
                                <div class="metric">
                                    <div class="label">Cloud Provider</div>
                                    <div class="value">{cloud_provider}</div>
                                </div>
                                <br/>
                                <div class="metric">
                                    <div class="label">Region</div>
                                    <div class="value">{region}</div>
                                </div>
                                <div class="metric">
                                    <div class="label">Assigned Team</div>
                                    <div class="value">{target_team}</div>
                                </div>
                            </div>
                        </div>

                        <div
                            style="background: #fef3c7; border-left: 4px solid #f59e0b;
                            padding: 12px; border-radius: 6px; margin: 12px 0;"
                        >
                            <strong>⚠️ Immediate Action Required</strong>
                            <p style="margin: 8px 0 0 0; color: #92400e;">
                                Review this alert immediately in the dashboard. The system has
                                identified potential security concerns that require investigation.
                            </p>
                        </div>

                        <a href="{dashboard_link}" class="button">Review in Dashboard</a>

                        <p style="margin-top: 20px; color: #6b7280; font-size: 13px;">
                            This is an automated alert from the CAPSTONE-189 Demo System.
                            For testing purposes, alerts are generated synthetically.
                        </p>
                    </div>
                    <div class="footer">
                        <p>© 2026 CAPSTONE-189 Security Operations Center</p>
                    </div>
                </div>
            </body>
        </html>
        """

        # Plain text version
        text = f"""
        SECURITY ALERT NOTIFICATION
        ============================

        A new security alert has been detected and requires your attention.

        Alert Summary:
        - Alert ID: {alert_id}
        - Entity ID: {entity_id}
        - Severity: {severity}
        - Risk Score: {score:.2%}
        - Cloud Provider: {cloud_provider}
        - Region: {region}
        - Assigned Team: {target_team}

        IMMEDIATE ACTION REQUIRED
        Review this alert immediately in the dashboard. The system has identified
        potential security concerns that require investigation.

        Dashboard: {dashboard_link}

        This is an automated alert from the CAPSTONE-189 Demo System.
        For testing purposes, alerts are generated synthetically.

        © 2026 CAPSTONE-189 Security Operations Center
        """

        return html, text

    @staticmethod
    async def send_alert_email(
        recipient_email: str, alert_data: Dict[str, Any], subject_override: Optional[str] = None
    ) -> bool:
        result = await EmailService.send_alert_email_result(
            recipient_email=recipient_email,
            alert_data=alert_data,
            subject_override=subject_override,
        )
        return bool(result["sent"])

    @staticmethod
    async def send_alert_email_result(
        recipient_email: str,
        alert_data: Dict[str, Any],
        subject_override: Optional[str] = None,
        settings: Optional[SmtpSettings] = None,
    ) -> Dict[str, Any]:
        """
        Send an alert email.

        Args:
            recipient_email: One address, or several separated by commas
            alert_data: Alert payload dictionary
            subject_override: Optional custom subject line
            settings: SMTP account to use; defaults to the environment settings

        Returns:
            Delivery result with success and error details.
        """
        settings = settings or SmtpSettings.from_env()
        try:
            if not settings.password:
                error_message = "No SMTP password is configured"
                print(f"✗ Failed to send email: {error_message}")
                return {"sent": False, "error": error_message}

            severity = alert_data.get("severity", "UNKNOWN")
            entity_id = alert_data.get("entity_id", "unknown")

            subject = subject_override or f"[{severity}] Security Alert - {entity_id}"

            html, text = EmailService.build_alert_html(alert_data, recipient_email)

            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = formataddr(("CAPSTONE-189 Alerts", settings.sender))
            message["To"] = recipient_email
            message.attach(MIMEText(text, "plain"))
            message.attach(MIMEText(html, "html"))

            # smtplib is blocking; run it in a worker thread so a slow SMTP
            # handshake does not stall every other request on the event loop.
            def _deliver() -> None:
                context = ssl.create_default_context()
                if settings.security == "ssl":
                    server = smtplib.SMTP_SSL(settings.host, settings.port, timeout=20, context=context)
                else:
                    server = smtplib.SMTP(settings.host, settings.port, timeout=20)
                with server:
                    if settings.security == "starttls":
                        server.starttls(context=context)
                    server.login(settings.username, settings.password)
                    server.send_message(message)

            await asyncio.to_thread(_deliver)

            print(f"✓ Email sent to {recipient_email}")
            return {"sent": True, "detail": f"Email sent to {recipient_email}"}

        except smtplib.SMTPAuthenticationError as e:
            if "gmail" in settings.host.lower():
                auth_hint = (
                    "Gmail rejected the login. Use the Gmail address that created the App "
                    "Password as the username, make sure 2-Step Verification is on, and paste "
                    "the 16-character App Password (not your normal Gmail password)."
                )
            else:
                auth_hint = "The SMTP server rejected the username or password."
            print(f"✗ Failed to send email to {recipient_email}: {str(e)}")
            return {"sent": False, "error": f"{auth_hint} SMTP says: {str(e)}"}

        except (OSError, smtplib.SMTPException) as e:
            print(f"✗ Failed to send email to {recipient_email}: {str(e)}")
            return {
                "sent": False,
                "error": (
                    f"Could not deliver through {settings.host}:{settings.port} "
                    f"({settings.security}): {e}"
                ),
            }

        except Exception as e:
            print(f"✗ Failed to send email to {recipient_email}: {str(e)}")
            return {"sent": False, "error": str(e)}
