import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone

from phase3.notifications.channel_notifiers import PagerDutyNotifier, SmsNotifier, WebhookNotifier
from shared.types import AlertPayload, EpisodeMatch, GroupType, NotifyMethod, Severity, SevLevel


BATCH_TS = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


def _sample_payload(alert_id: str = "alert-1", severity: Severity = Severity.CRITICAL) -> AlertPayload:
    return AlertPayload(
        alert_id=alert_id,
        entity_id="vm-1",
        batch_ts=BATCH_TS,
        final_score=0.82,
        severity=severity,
        sev_level=SevLevel.SEV1,
        deviation_score=0.8,
        drift_score=0.7,
        similarity_score=0.5,
        similar_episodes=[
            EpisodeMatch(
                similarity_score=0.91,
                episode_id="ep-1",
                entity_id="vm-1",
                timestamp=BATCH_TS,
                cloud_provider="AWS",
                severity_label="CRITICAL",
            )
        ],
        related_ids=["incident-9"],
        group_type=GroupType.REGIONAL_OUTAGE,
        target_team="on_call",
        notify_method=NotifyMethod.PAGE,
        cloud_provider="AWS",
        region="us-east-1",
    )


class FakeHttpClient:
    def __init__(self):
        self.calls = []

    async def post(self, url, *, json=None, data=None, headers=None):
        self.calls.append({
            "url": url,
            "json": json,
            "data": data,
            "headers": headers,
        })

        class _Response:
            status_code = 202
            text = "ok"

        return _Response()


def test_webhook_notifier_signs_payload_and_posts_json():
    async def _run():
        client = FakeHttpClient()
        secret = "super-secret-key-123456"
        notifier = WebhookNotifier(url="https://hooks.example.test/ingest", secret=secret, http_client=client)

        result = await notifier.notify(_sample_payload())

        assert result["success"] is True
        assert len(client.calls) == 1
        call = client.calls[0]
        assert call["url"] == "https://hooks.example.test/ingest"
        assert call["headers"]["Content-Type"] == "application/json"
        assert "X-Capstone-Signature" in call["headers"]
        body = json.dumps(call["json"], sort_keys=True)
        expected = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        assert call["headers"]["X-Capstone-Signature"] == expected

    asyncio.run(_run())


def test_sms_notifier_requires_critical_and_skips_noncritical():
    async def _run():
        client = FakeHttpClient()
        notifier = SmsNotifier(
            phone_number="MASKED_PHONE",
            http_client=client,
            allow_after_hours=False,
            now_provider=lambda: datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        )

        skipped = await notifier.notify(_sample_payload(severity=Severity.HIGH))
        assert skipped["success"] is False
        assert "critical" in skipped["detail"].lower()
        assert client.calls == []

        sent = await notifier.notify(_sample_payload(severity=Severity.CRITICAL))
        assert sent["success"] is True
        assert client.calls

    asyncio.run(_run())


def test_pagerduty_notifier_builds_event_payload():
    async def _run():
        client = FakeHttpClient()
        notifier = PagerDutyNotifier(routing_key="abc123", http_client=client)

        result = await notifier.notify(_sample_payload())

        assert result["success"] is True
        call = client.calls[0]
        assert call["url"] == "https://events.pagerduty.com/v2/enqueue"
        event = call["json"]
        assert event["routing_key"] == "abc123"
        assert event["dedup_key"] == "pd:vm-1"
        assert event["payload"]["severity"] == "critical"
        assert event["payload"]["source"] == "vm-1"

    asyncio.run(_run())
