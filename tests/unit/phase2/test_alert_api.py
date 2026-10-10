import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from phase2.alerting.api.alert_api import create_app
from phase2.alerting.api.dispatcher import NotificationDispatcher
from phase2.alerting.api.models import AlertPayloadModel
from phase2.alerting.api.payload_builder import build_alert_payload
from phase2.alerting.api.recent_alerts_store import RecentAlertsStore
from phase2.alerting.notifiers.base_notifier import BaseNotifier
from phase2.alerting.notifiers.dashboard_writer import DashboardWriter, InMemoryDashboardStore
from shared.types import (
    AnomalyResult,
    CorrelationResult,
    EpisodeMatch,
    EscalationResult,
    GroupType,
    NotifyMethod,
    Severity,
    SevLevel,
)


BATCH_TS = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


def make_anomaly_result(entity_id: str = "vm-1") -> AnomalyResult:
    return AnomalyResult(
        entity_id=entity_id,
        final_score=0.82,
        severity=Severity.CRITICAL,
        deviation_contribution=0.32,   # 0.4 * 0.8
        drift_contribution=0.28,       # 0.4 * 0.7
        similarity_contribution=0.10,  # 0.2 * (1 - 0.5)
        batch_ts=BATCH_TS,
    )


def make_escalation_result(entity_id: str = "vm-1") -> EscalationResult:
    return EscalationResult(
        entity_id=entity_id,
        sev_level=SevLevel.SEV1,
        target_team="on_call",
        notify_method=NotifyMethod.PAGE,
        policy_applied="critical_regional_page",
        business_hours_flag=True,
    )


def make_correlation_result(entity_id: str = "vm-1") -> CorrelationResult:
    return CorrelationResult(
        entity_id=entity_id,
        incident_group_id="grp_abc123",
        related_ids=["incident-9"],
        group_size=12,
        group_type=GroupType.REGIONAL_OUTAGE,
    )


def make_episode(entity_id: str = "vm-2") -> EpisodeMatch:
    return EpisodeMatch(
        similarity_score=0.91,
        episode_id="ep-1",
        entity_id=entity_id,
        timestamp=BATCH_TS,
        cloud_provider="AWS",
        severity_label="CRITICAL",
    )


# ── payload_builder ──────────────────────────────────────────────────────────


def test_build_alert_payload_recovers_component_scores_from_contributions():
    payload = build_alert_payload(
        anomaly_result=make_anomaly_result(),
        escalation_result=make_escalation_result(),
        correlation_result=make_correlation_result(),
        similar_episodes=[make_episode()],
        cloud_provider="AWS",
        region="us-east-1",
    )

    assert payload.entity_id == "vm-1"
    assert payload.deviation_score == pytest.approx(0.8, abs=1e-6)
    assert payload.drift_score == pytest.approx(0.7, abs=1e-6)
    assert payload.similarity_score == pytest.approx(0.5, abs=1e-6)
    assert payload.sev_level == SevLevel.SEV1
    assert payload.group_type == GroupType.REGIONAL_OUTAGE
    assert payload.related_ids == ["incident-9"]
    assert len(payload.similar_episodes) == 1
    assert payload.similar_episodes[0].episode_id == "ep-1"
    assert payload.component_breakdown["deviation_score"] == pytest.approx(0.8, abs=1e-6)


def test_build_alert_payload_rejects_entity_id_mismatch():
    with pytest.raises(ValueError):
        build_alert_payload(
            anomaly_result=make_anomaly_result("vm-1"),
            escalation_result=make_escalation_result("vm-DIFFERENT"),
            correlation_result=make_correlation_result("vm-1"),
            similar_episodes=[],
            cloud_provider="AWS",
            region="us-east-1",
        )


# ── NotificationDispatcher fault isolation ───────────────────────────────────


class _AlwaysSucceedsNotifier(BaseNotifier):
    def __init__(self, name: str):
        super().__init__(channel_name=name)

    async def _send(self, payload: AlertPayloadModel) -> str:
        return "ok"


class _AlwaysRaisesNotifier(BaseNotifier):
    def __init__(self, name: str):
        super().__init__(channel_name=name)

    async def _send(self, payload: AlertPayloadModel) -> str:
        raise RuntimeError("simulated channel outage")


def test_dispatcher_isolates_failing_channel_from_succeeding_ones():
    payload = build_alert_payload(
        anomaly_result=make_anomaly_result(),
        escalation_result=make_escalation_result(),
        correlation_result=make_correlation_result(),
        similar_episodes=[],
        cloud_provider="AWS",
        region="us-east-1",
    )
    dispatcher = NotificationDispatcher(
        [_AlwaysSucceedsNotifier("slack"), _AlwaysRaisesNotifier("email")]
    )

    outcomes = asyncio.run(dispatcher.dispatch(payload))

    assert outcomes["slack"].success is True
    assert outcomes["email"].success is False
    assert "simulated channel outage" in outcomes["email"].detail


# ── FastAPI app ──────────────────────────────────────────────────────────────


def _payload_json(entity_id: str = "vm-1") -> dict:
    payload = build_alert_payload(
        anomaly_result=make_anomaly_result(entity_id),
        escalation_result=make_escalation_result(entity_id),
        correlation_result=make_correlation_result(entity_id),
        similar_episodes=[make_episode()],
        cloud_provider="AWS",
        region="us-east-1",
    )
    return payload.model_dump(mode="json")


def test_post_alert_dispatches_and_lists_in_recent_alerts():
    dashboard_store = InMemoryDashboardStore()
    app = create_app(
        notifiers=[DashboardWriter(dashboard_store), _AlwaysSucceedsNotifier("pagerduty")],
        recent_alerts_store=RecentAlertsStore(redis_client=None),
    )
    client = TestClient(app)

    response = client.post("/alert", json=_payload_json())
    assert response.status_code == 200
    body = response.json()
    assert body["all_succeeded"] is True
    assert set(body["dispatch_status"].keys()) == {"dashboard", "pagerduty"}

    recent = client.get("/alerts/recent").json()
    assert len(recent) == 1
    assert recent[0]["entity_id"] == "vm-1"
    assert len(dashboard_store.all_points()) == 1


def test_post_alert_slack_only_severity_skips_pagerduty_channel():
    app = create_app(notifiers=[_AlwaysSucceedsNotifier("pagerduty"), _AlwaysSucceedsNotifier("dashboard")])
    client = TestClient(app)

    payload = _payload_json()
    payload["notify_method"] = "SLACK"  # no slack notifier configured -> empty selection + dashboard

    response = client.post("/alert", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert "pagerduty" not in body["dispatch_status"]
    assert "dashboard" in body["dispatch_status"]


def test_healthz_reports_configured_notifiers():
    app = create_app(notifiers=[_AlwaysSucceedsNotifier("slack")])
    client = TestClient(app)

    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["notifiers"] == ["slack"]


def test_dashboard_page_served_at_root():
    app = create_app()
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "Explainable Alert Dashboard" in response.text
