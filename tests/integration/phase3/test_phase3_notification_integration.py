import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from phase2.alerting.api.alert_api import create_app
from phase2.alerting.api.models import AlertPayloadModel
from shared.types import GroupType, NotifyMethod, Severity, SevLevel


BATCH_TS = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


class _RecordingNotifier:
    def __init__(self, channel: str):
        self.channel_name = channel
        self.calls = []

    async def notify(self, payload):
        self.calls.append(payload.alert_id)
        return {"channel": self.channel_name, "success": True, "detail": "ok"}


def test_dispatcher_with_fake_notifiers_and_in_memory_recorder():
    from phase3.notifications.notification_dispatcher import NotificationDispatcher
    from phase3.shared.types import NotificationEndpoint, NotificationPolicy

    async def _run():
        notifier = _RecordingNotifier("slack")
        dispatcher = NotificationDispatcher(
            notifiers=[notifier],
            endpoints=[NotificationEndpoint(endpoint_id="ep-1", tenant_id="tenant-a", channel="slack", target="https://hooks.slack.test/abc", enabled=True)],
        )

        payload = AlertPayloadModel(
            alert_id=uuid4(),
            entity_id="vm-1",
            batch_ts=BATCH_TS,
            final_score=0.8,
            severity=Severity.HIGH,
            sev_level=SevLevel.SEV2,
            deviation_score=0.7,
            drift_score=0.5,
            similarity_score=0.6,
            similar_episodes=[],
            related_ids=["incident-1"],
            group_type=GroupType.ISOLATED,
            target_team="on_call",
            notify_method=NotifyMethod.SLACK,
            cloud_provider="AWS",
            region="us-east-1",
        )

        results = await dispatcher.dispatch(payload, NotificationPolicy(tenant_id="tenant-a"))

        assert len(results) == 1
        assert results[0].success is True
        assert notifier.calls == [payload.alert_id]

    asyncio.run(_run())


def test_alert_api_supports_injected_dispatcher_and_legacy_fallback():
    from phase3.notifications.notification_dispatcher import NotificationDispatcher
    from phase3.shared.types import NotificationEndpoint, NotificationPolicy

    app = create_app(notifiers=[], notification_dispatcher=NotificationDispatcher(
        notifiers=[_RecordingNotifier("slack")],
        endpoints=[NotificationEndpoint(endpoint_id="ep-1", tenant_id="tenant-a", channel="slack", target="https://hooks.slack.test/abc", enabled=True)],
    ))

    payload = {
        "alert_id": str(uuid4()),
        "entity_id": "vm-2",
        "batch_ts": BATCH_TS.isoformat(),
        "final_score": 0.75,
        "severity": "HIGH",
        "sev_level": "SEV2",
        "deviation_score": 0.7,
        "drift_score": 0.5,
        "similarity_score": 0.6,
        "similar_episodes": [],
        "related_ids": [],
        "group_type": "ISOLATED",
        "target_team": "on_call",
        "notify_method": "SLACK",
        "cloud_provider": "AWS",
        "region": "us-east-1",
    }

    with TestClient(app) as client:
        response = client.post("/alert", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["alert_id"] == payload["alert_id"]

    legacy_app = create_app(notifiers=[])
    with TestClient(legacy_app) as client:
        response = client.post("/alert", json=payload)
        assert response.status_code == 200
