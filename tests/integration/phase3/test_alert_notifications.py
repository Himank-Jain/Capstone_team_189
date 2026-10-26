"""Outbound notification channels report real outcomes and never fake success."""

import pytest
from fastapi.testclient import TestClient

from phase3.api import alert_notifications
from phase3.api.app import app
from phase3.api.email_service import EmailService
from phase3.api.routers import _support
from phase3.db.models import Base
from phase3.db.session import PlatformSessionFactory

PASSWORD = "Corr3ct-Horse!"


class _FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    def __init__(self, sink, status_code=200):
        self._sink = sink
        self._status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self._sink.append({"url": url, "json": json, "headers": headers or {}})
        return _FakeResponse(self._status_code, "upstream said no")


@pytest.fixture
def client(tmp_path, monkeypatch):
    factory = PlatformSessionFactory({"database_url": f"sqlite:///{tmp_path / 'notify.db'}"})
    Base.metadata.create_all(factory.build_engine())
    monkeypatch.setattr(_support, "platform_session_factory", factory)
    monkeypatch.setenv("CAPSTONE_AUTH_REQUIRED", "true")
    monkeypatch.setenv("PLATFORM_JWT_SECRET", "test-secret-that-is-definitely-longer-than-32-bytes")
    monkeypatch.setenv("PLATFORM_BCRYPT_ROUNDS", "4")
    for name in (
        "DEMO_EMAIL_RECIPIENT",
        "DEMO_EMAIL_SENDER",
        "DEMO_EMAIL_PASSWORD",
        "SLACK_WEBHOOK_URL",
        "ALERT_WEBHOOK_URL",
        "ALERT_WEBHOOK_SECRET",
        "PAGERDUTY_ROUTING_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    _support.reset_auth_service()
    with TestClient(app) as test_client:
        yield test_client
    _support.reset_auth_service()


def _session(test_client, email):
    response = test_client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}", "X-Tenant-Id": "google"}


def test_unconfigured_channels_are_reported_as_such_and_never_as_sent(client):
    owner = _session(client, "owner@example.com")

    statuses = {
        item["channel"]: item["status"]
        for item in client.get("/notifications/channels", headers=owner).json()
    }
    slack = client.post("/notifications/test", headers=owner, json={"channel": "SLACK"}).json()
    email = client.post("/notifications/test", headers=owner, json={"channel": "EMAIL"}).json()

    assert statuses["PAGE"] == "ready"
    assert statuses["SLACK"] == "credentials_required"
    assert statuses["EMAIL"] == "credentials_required"
    assert slack["status"] == "not_configured" and slack["sent"] is False
    assert email["status"] == "not_configured" and email["sent"] is False
    assert email["email_to"] == "owner@example.com"


def test_slack_webhook_receives_alert_and_http_errors_surface(client, monkeypatch):
    owner = _session(client, "owner@example.com")
    posted = []
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/services/T/B/X")
    monkeypatch.setattr(alert_notifications, "http_client_factory", lambda: _FakeClient(posted))

    ok = client.post("/notifications/test", headers=owner, json={"channel": "slack"}).json()

    assert ok["status"] == "sent"
    assert posted[0]["url"] == "https://hooks.slack.test/services/T/B/X"
    assert "notification-test" in posted[0]["json"]["text"]

    monkeypatch.setattr(
        alert_notifications, "http_client_factory", lambda: _FakeClient(posted, status_code=403)
    )
    failed = client.post("/notifications/test", headers=owner, json={"channel": "SLACK"}).json()
    assert failed["status"] == "failed"
    assert "HTTP 403" in failed["message"]


class _FakeSMTP:
    """Stands in for smtplib.SMTP / SMTP_SSL and records what would be sent."""

    sent = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.tls, self.login_as = host, port, False, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, username, password):
        if password != "app-password-1234":
            import smtplib

            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.login_as = username

    def send_message(self, message):
        _FakeSMTP.sent.append(
            {"host": self.host, "port": self.port, "tls": self.tls, "login": self.login_as,
             "to": message["To"], "from": message["From"], "subject": message["Subject"]}
        )


@pytest.fixture
def fake_smtp(monkeypatch):
    from phase3.api import email_service

    _FakeSMTP.sent = []
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", _FakeSMTP)
    return _FakeSMTP


def test_test_email_goes_only_to_the_requester_and_alerts_to_every_member(client, monkeypatch, fake_smtp):
    owner = {**_session(client, "owner@example.com"), "X-Tenant-Id": "acme"}
    _session(client, "teammate@example.com")
    monkeypatch.setenv("DEMO_EMAIL_SENDER", "alerts@example.com")
    monkeypatch.setenv("DEMO_EMAIL_PASSWORD", "app-password-1234")

    result = client.post("/notifications/test", headers=owner, json={"channel": "EMAIL"}).json()
    assert result["status"] == "sent", result
    assert fake_smtp.sent[-1]["to"] == "owner@example.com"
    assert fake_smtp.sent[-1]["subject"].startswith("[TEST]")
    assert fake_smtp.sent[-1]["host"] == "smtp.gmail.com" and fake_smtp.sent[-1]["tls"] is True

    try:
        alert = client.post(
            "/demo/generate/alert",
            headers=owner,
            json={"tenant_id": "acme", "scenario": "credential_theft", "notify_method": "EMAIL"},
        )
        assert alert.status_code == 200, alert.text
        assert alert.json()["notification"]["status"] == "sent"
        assert fake_smtp.sent[-1]["to"] == "owner@example.com, teammate@example.com"
    finally:
        assert client.post("/demo/reset", headers=owner).status_code == 200


def test_workspace_email_settings_are_owner_only_and_never_reveal_the_password(client, fake_smtp):
    from phase3.api.alert_notifications import load_workspace_email_settings

    owner = _session(client, "owner@example.com")
    viewer = _session(client, "viewer@example.com")
    body = {
        "host": "smtp.office365.com", "port": 587, "security": "starttls",
        "username": "alerts@contoso.example", "password": "app-password-1234",
        "recipients": ["soc@contoso.example"],
    }

    assert client.put("/notifications/email-settings", headers=viewer, json=body).status_code == 403
    saved = client.put("/notifications/email-settings", headers=owner, json=body)
    assert saved.status_code == 200, saved.text
    summary = saved.json()
    assert summary["source"] == "workspace" and summary["ready"] is True
    assert summary["password_set"] is True
    assert "app-password-1234" not in saved.text
    stored = load_workspace_email_settings("google")
    assert "app-password-1234" not in str(stored)
    assert stored["password_ciphertext"]

    # Viewers can read the (password-free) summary.
    assert client.get("/notifications/email-settings", headers=viewer).json()["host"] == "smtp.office365.com"

    # A blank password keeps the saved one; other fields update.
    updated = client.put(
        "/notifications/email-settings", headers=owner,
        json={**body, "password": "", "port": 465, "security": "ssl"},
    ).json()
    assert updated["port"] == 465 and updated["password_set"] is True

    statuses = {item["channel"]: item for item in client.get("/notifications/channels", headers=owner).json()}
    assert statuses["EMAIL"]["status"] == "ready"
    assert "smtp.office365.com" in statuses["EMAIL"]["detail"]

    result = client.post("/notifications/test", headers=owner, json={"channel": "EMAIL"}).json()
    assert result["status"] == "sent", result
    assert fake_smtp.sent[-1]["host"] == "smtp.office365.com" and fake_smtp.sent[-1]["port"] == 465
    assert fake_smtp.sent[-1]["login"] == "alerts@contoso.example"

    cleared = client.delete("/notifications/email-settings", headers=owner).json()
    assert cleared["source"] == "none" and cleared["ready"] is False


def test_wrong_smtp_password_is_reported_with_a_hint(client, fake_smtp):
    owner = _session(client, "owner@example.com")
    client.put(
        "/notifications/email-settings", headers=owner,
        json={"host": "smtp.gmail.com", "port": 587, "security": "starttls",
              "username": "me@gmail.com", "password": "my-normal-password"},
    )
    result = client.post("/notifications/test", headers=owner, json={"channel": "EMAIL"}).json()
    assert result["status"] == "failed"
    assert "App Password" in result["message"]


def test_email_settings_validation(client):
    owner = _session(client, "owner@example.com")
    missing_password = client.put(
        "/notifications/email-settings", headers=owner,
        json={"host": "smtp.example.com", "username": "alerts@example.com"},
    )
    bad_recipient = client.put(
        "/notifications/email-settings", headers=owner,
        json={"host": "smtp.example.com", "username": "alerts@example.com", "password": "x" * 12,
              "recipients": ["not-an-email"]},
    )
    assert missing_password.status_code == 422
    assert bad_recipient.status_code == 422


def test_signed_webhook_and_viewer_cannot_send_tests(client, monkeypatch):
    import hashlib
    import hmac
    import json

    owner = _session(client, "owner@example.com")
    viewer = _session(client, "viewer@example.com")
    posted = []
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://siem.example.test/ingest")
    monkeypatch.setenv("ALERT_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(alert_notifications, "http_client_factory", lambda: _FakeClient(posted))

    assert client.post("/notifications/test", headers=viewer, json={"channel": "WEBHOOK"}).status_code == 403
    result = client.post("/notifications/test", headers=owner, json={"channel": "WEBHOOK"}).json()

    assert result["status"] == "sent"
    body = posted[0]["json"]
    expected = hmac.new(b"s3cret", json.dumps(body, sort_keys=True).encode(), hashlib.sha256).hexdigest()
    assert posted[0]["headers"]["X-Capstone-Signature"] == expected


def test_demo_alert_records_chosen_channel_on_the_incident(client, monkeypatch):
    owner = {**_session(client, "owner@example.com"), "X-Tenant-Id": "oracle"}
    posted = []
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/services/T/B/X")
    monkeypatch.setattr(alert_notifications, "http_client_factory", lambda: _FakeClient(posted))

    try:
        _assert_slack_delivery_recorded(client, owner, posted)
    finally:
        # The demo engine keeps per-tenant state in module globals; leave none behind.
        assert client.post("/demo/reset", headers=owner).status_code == 200


def _assert_slack_delivery_recorded(client, owner, posted):
    response = client.post(
        "/demo/generate/alert",
        headers=owner,
        json={"tenant_id": "oracle", "scenario": "credential_theft", "notify_method": "SLACK"},
    )
    assert response.status_code == 200, response.text
    alert_id = response.json()["alert_payload"]["alert_id"]
    assert response.json()["notification"]["status"] == "sent"

    investigation = client.get(f"/incidents/{alert_id}/investigation", headers=owner).json()
    channels = {item["channel"]: item for item in investigation["notification_deliveries"]}
    assert channels["SLACK"]["success"] is True
    assert "PAGE" in {str(key).upper() for key in channels}
    assert alert_id in posted[0]["json"]["blocks"][1]["elements"][0]["text"]
