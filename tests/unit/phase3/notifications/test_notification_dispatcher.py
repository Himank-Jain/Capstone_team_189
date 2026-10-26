import asyncio
from datetime import datetime, timezone

from phase3.shared.types import (
    NotificationEndpoint,
    NotificationPolicy,
)
from shared.types import AlertPayload, EpisodeMatch, GroupType, NotifyMethod, Severity, SevLevel


BATCH_TS = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


def _sample_payload(alert_id: str = "alert-1", tenant_id: str = "tenant-a") -> AlertPayload:
    return AlertPayload(
        alert_id=alert_id,
        entity_id="vm-1",
        batch_ts=BATCH_TS,
        final_score=0.82,
        severity=Severity.CRITICAL,
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


class _FakeNotifier:
    def __init__(self, channel: str, *, delay: float = 0.0, fail: bool = False):
        self.channel_name = channel
        self.delay = delay
        self.fail = fail

    async def notify(self, payload):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError(f"{self.channel_name} failed")
        return {"channel": self.channel_name, "success": True, "detail": "ok"}


def test_severity_filtering_and_channel_filtering():
    from phase3.notifications.notification_dispatcher import NotificationDispatcher

    async def _run():
        policy = NotificationPolicy(
            tenant_id="tenant-a",
            min_severity=Severity.HIGH,
            allowed_channels=["email", "slack"],
        )

        dispatcher = NotificationDispatcher(
            notifiers=[_FakeNotifier("slack"), _FakeNotifier("email"), _FakeNotifier("pagerduty")],
            endpoints=[
                NotificationEndpoint(
                    endpoint_id="e1",
                    tenant_id="tenant-a",
                    channel="slack",
                    target="https://hooks.slack.test/abc",
                    enabled=True,
                ),
                NotificationEndpoint(
                    endpoint_id="e2",
                    tenant_id="tenant-a",
                    channel="email",
                    target="ops@example.com",
                    enabled=True,
                ),
                NotificationEndpoint(
                    endpoint_id="e3",
                    tenant_id="tenant-a",
                    channel="pagerduty",
                    target="pagerduty-route",
                    enabled=True,
                ),
            ],
        )

        results = await dispatcher.dispatch(_sample_payload(), policy)
        channels = {r.channel for r in results}
        assert {"slack", "email"} == channels
        assert all(r.success for r in results)

    asyncio.run(_run())


def test_quiet_hours_skip_and_no_exception_escapes():
    from phase3.notifications.notification_dispatcher import NotificationDispatcher

    async def _run():
        now = datetime.now(timezone.utc)
        start_hour = (now.hour + 23) % 24
        end_hour = (now.hour + 1) % 24
        policy = NotificationPolicy(
            tenant_id="tenant-a",
            quiet_hours_start=f"{start_hour:02d}:00",
            quiet_hours_end=f"{end_hour:02d}:00",
            quiet_hours_tz="UTC",
        )

        payload = _sample_payload()
        dispatcher = NotificationDispatcher(
            notifiers=[_FakeNotifier("slack")],
            endpoints=[
                NotificationEndpoint(
                    endpoint_id="e1",
                    tenant_id="tenant-a",
                    channel="slack",
                    target="https://hooks.slack.test/abc",
                    enabled=True,
                )
            ],
        )

        results = await dispatcher.dispatch(payload, policy)
        assert results == [] or all(r.success is False or r.channel != "slack" for r in results)

    asyncio.run(_run())


def test_one_failing_channel_does_not_block_others_and_timeout_isolation():
    from phase3.notifications.notification_dispatcher import NotificationDispatcher

    async def _run():
        payload = _sample_payload()
        dispatcher = NotificationDispatcher(
            notifiers=[
                _FakeNotifier("slack", delay=0.1),
                _FakeNotifier("email", delay=0.5, fail=True),
            ],
            endpoints=[
                NotificationEndpoint(
                    endpoint_id="e1",
                    tenant_id="tenant-a",
                    channel="slack",
                    target="https://hooks.slack.test/abc",
                    enabled=True,
                ),
                NotificationEndpoint(
                    endpoint_id="e2",
                    tenant_id="tenant-a",
                    channel="email",
                    target="ops@example.com",
                    enabled=True,
                ),
            ],
        )

        results = await dispatcher.dispatch(
            payload, NotificationPolicy(tenant_id="tenant-a"), timeout_seconds=0.2
        )
        by_channel = {r.channel: r for r in results}
        assert by_channel["slack"].success is True
        assert by_channel["email"].success is False
        assert by_channel["email"].error is not None

    asyncio.run(_run())


def test_idempotent_double_dispatch_sends_once_and_records_retry_count():
    from phase3.notifications.notification_dispatcher import NotificationDispatcher

    async def _run():
        payload = _sample_payload(alert_id="alert-42")
        dispatcher = NotificationDispatcher(
            notifiers=[_FakeNotifier("slack")],
            endpoints=[
                NotificationEndpoint(
                    endpoint_id="e1",
                    tenant_id="tenant-a",
                    channel="slack",
                    target="https://hooks.slack.test/abc",
                    enabled=True,
                )
            ],
        )

        first = await dispatcher.dispatch(payload, NotificationPolicy(tenant_id="tenant-a"))
        second = await dispatcher.dispatch(payload, NotificationPolicy(tenant_id="tenant-a"))

        assert len(first) == 1
        assert len(second) == 0
        assert first[0].retry_count >= 0

    asyncio.run(_run())


def test_resolved_delivery_uses_lifecycle_idempotency_key():
    from phase3.notifications.notification_dispatcher import NotificationDispatcher

    class _KeyRecorder:
        def __init__(self):
            self.keys = []

        async def acquire(self, key, ttl_seconds):
            self.keys.append(key)
            return True

    async def _run():
        key_recorder = _KeyRecorder()
        dispatcher = NotificationDispatcher(
            notifiers=[_FakeNotifier("page")],
            endpoints=[
                NotificationEndpoint(
                    endpoint_id="endpoint-9", tenant_id="tenant-a", channel="page", target="dash"
                )
            ],
            idempotency_store=key_recorder,
        )
        await dispatcher.dispatch(
            _sample_payload("alert-42"),
            NotificationPolicy(tenant_id="tenant-a", allowed_channels=["page"]),
            idempotency_suffix="resolved",
        )
        assert key_recorder.keys == ["alert-42:endpoint-9:resolved"]

    asyncio.run(_run())


def test_tenant_scoping_restricts_endpoints():
    from phase3.notifications.notification_dispatcher import NotificationDispatcher

    async def _run():
        payload = _sample_payload()
        dispatcher = NotificationDispatcher(
            notifiers=[_FakeNotifier("slack")],
            endpoints=[
                NotificationEndpoint(
                    endpoint_id="e1",
                    tenant_id="tenant-b",
                    channel="slack",
                    target="https://hooks.slack.test/b",
                    enabled=True,
                ),
                NotificationEndpoint(
                    endpoint_id="e2",
                    tenant_id="tenant-a",
                    channel="slack",
                    target="https://hooks.slack.test/a",
                    enabled=True,
                ),
            ],
        )

        results = await dispatcher.dispatch(payload, NotificationPolicy(tenant_id="tenant-a"))
        labels = {r.endpoint_id for r in results}
        assert labels == {"e2"}

    asyncio.run(_run())


def test_masked_logging_does_not_expose_full_target(caplog):
    from phase3.notifications.notification_dispatcher import NotificationDispatcher

    policy = NotificationPolicy(tenant_id="tenant-a")
    payload = _sample_payload()
    dispatcher = NotificationDispatcher(
        notifiers=[_FakeNotifier("slack")],
        endpoints=[
            NotificationEndpoint(
                endpoint_id="e1",
                tenant_id="tenant-a",
                channel="slack",
                target="https://hooks.slack.test/secret-token",
                enabled=True,
            )
        ],
    )

    with caplog.at_level("INFO"):
        asyncio.run(dispatcher.dispatch(payload, policy))

    assert "https://hooks.slack.test/secret-token" not in caplog.text
    assert "hooks.slack.test" not in caplog.text
