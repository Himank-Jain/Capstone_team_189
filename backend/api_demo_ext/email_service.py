"""Email notification service for demo alerts."""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional


_TENANT_EMAIL_DEFAULTS = {
    "google": "ops@google-demo.internal",
    "microsoft": "security@microsoft-demo.internal",
    "amazon": "security@amazon-demo.internal",
    "oracle": "soc@oracle-demo.internal",
    "openai": "alerts@openai-demo.internal",
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
                    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: #0b0f17; color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                    .header h1 {{ margin: 0; font-size: 24px; }}
                    .content {{ background: #f9fafb; padding: 20px; border-radius: 0 0 8px 8px; border: 1px solid #e5e7eb; }}
                    .alert-box {{ background: white; padding: 16px; border-radius: 8px; margin: 12px 0; border-left: 4px solid {severity_color}; }}
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
                    .footer {{ color: #6b7280; font-size: 12px; margin-top: 20px; text-align: center; }}
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
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                                <h2 style="margin: 0; font-size: 18px;">Alert Summary</h2>
                                <span class="severity-badge">{severity}</span>
                            </div>
                            
                            <div style="border-top: 1px solid #e5e7eb; padding-top: 12px;">
                                <div class="metric">
                                    <div class="label">Alert ID</div>
                                    <div class="value" style="font-family: monospace; font-size: 12px;">{alert_id}</div>
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
                        
                        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px; border-radius: 6px; margin: 12px 0;">
                            <strong>⚠️ Immediate Action Required</strong>
                            <p style="margin: 8px 0 0 0; color: #92400e;">Review this alert immediately in the dashboard. The system has identified potential security concerns that require investigation.</p>
                        </div>
                        
                        <a href="http://127.0.0.1:5173/" class="button">Review in Dashboard</a>
                        
                        <p style="margin-top: 20px; color: #6b7280; font-size: 13px;">
                            This is an automated alert from the CAPSTONE-189 Demo System. 
                            For testing purposes, alerts are generated synthetically.
                        </p>
                    </div>
                    <div class="footer">
                        <p>© 2024 CAPSTONE-189 Security Operations Center</p>
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
        
        Dashboard: http://127.0.0.1:5173/
        
        This is an automated alert from the CAPSTONE-189 Demo System.
        For testing purposes, alerts are generated synthetically.
        
        © 2024 CAPSTONE-189 Security Operations Center
        """
        
        return html, text
    
    @staticmethod
    async def send_alert_email(
        recipient_email: str,
        alert_data: Dict[str, Any],
        subject_override: Optional[str] = None
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
        subject_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send alert email asynchronously.
        
        Args:
            recipient_email: Email address to send to
            alert_data: Alert payload dictionary
            subject_override: Optional custom subject line
            
        Returns:
            Delivery result with success and error details.
        """
        try:
            sender_email = EmailService.resolve_sender_email()
            sender_password = EmailService.resolve_sender_password()

            if not sender_password:
                error_message = "DEMO_EMAIL_PASSWORD is not configured"
                print(f"✗ Failed to send email: {error_message}")
                return {"sent": False, "error": error_message}

            severity = alert_data.get("severity", "UNKNOWN")
            entity_id = alert_data.get("entity_id", "unknown")

            subject = subject_override or f"[{severity}] Security Alert - {entity_id}"

            html, text = EmailService.build_alert_html(alert_data, recipient_email)

            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = sender_email
            message["To"] = recipient_email

            # Attach both plain text and HTML versions
            part1 = MIMEText(text, "plain")
            part2 = MIMEText(html, "html")
            message.attach(part1)
            message.attach(part2)

            # Send email via SMTP
            # Note: This is a synchronous operation wrapped in async
            # For production, consider using an async email library
            with smtplib.SMTP(EmailService.SMTP_SERVER, EmailService.SMTP_PORT) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(message)

            print(f"✓ Email sent to {recipient_email}")
            return {"sent": True, "detail": f"Email sent to {recipient_email}"}

        except smtplib.SMTPAuthenticationError as e:
            auth_hint = (
                "Gmail authentication failed. Verify DEMO_EMAIL_SENDER is the same Gmail account "
                "that generated the App Password, ensure 2-Step Verification is enabled, and paste "
                "the 16-character App Password (spaces allowed; backend normalizes them)."
            )
            print(f"✗ Failed to send email to {recipient_email}: {str(e)}")
            return {"sent": False, "error": f"{auth_hint} SMTP says: {str(e)}"}

        except Exception as e:
            print(f"✗ Failed to send email to {recipient_email}: {str(e)}")
            return {"sent": False, "error": str(e)}
