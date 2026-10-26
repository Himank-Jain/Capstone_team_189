import asyncio

from phase3.lifecycle.incident_resolution_service import IncidentResolutionService
from phase3.shared.types import ResolutionType


class _Recorder:
    def __init__(self, name, events):
        self.name = name
        self.events = events

    def reset_entity(self, entity_id):
        self.events.append((self.name, entity_id))

    def remove_entity(self, tenant_id, entity_id):
        self.events.append((self.name, tenant_id, entity_id))

    def resolve(self, tenant_id, entity_id, resolution_type):
        self.events.append((self.name, tenant_id, entity_id, resolution_type))

    def freeze(self, tenant_id, entity_id):
        self.events.append((self.name, tenant_id, entity_id))

    def invalidate(self, tenant_id, entity_id):
        self.events.append((self.name, tenant_id, entity_id))

    def clear_group(self, incident_group_id):
        self.events.append((self.name, incident_group_id))

    def record(self, tenant_id, incident_id, actor_user_id, action, details):
        self.events.append((self.name, tenant_id, incident_id, actor_user_id, action, details))


class _FailingNotification:
    async def send_resolved(self, tenant_id, incident_id, entity_id):
        raise RuntimeError("notification channel unavailable")


def test_resolve_resets_each_side_effect_and_contains_notification_failure(caplog):
    events = []
    service = IncidentResolutionService(
        dedup=_Recorder("dedup", events),
        correlation=_Recorder("correlation", events),
        entity_recovery=_Recorder("baseline", events),
        drift_cache=_Recorder("drift", events),
        notification_dispatcher=_FailingNotification(),
        audit_logger=_Recorder("audit", events),
        escalation_memory=_Recorder("escalation", events),
    )

    asyncio.run(
        service.resolve(
            "tenant-a",
            "incident-a",
            "entity-a",
            "operator-a",
            ResolutionType.FIXED,
            "group-a",
        )
    )

    assert ("dedup", "entity-a") in events
    assert ("escalation", "group-a") in events
    assert ("correlation", "tenant-a", "entity-a") in events
    assert ("drift", "tenant-a", "entity-a") in events
    assert (
        "baseline",
        "tenant-a",
        "entity-a",
        ResolutionType.FIXED,
    ) in events
    assert any(event[0] == "audit" and event[4] == "incident_resolved" for event in events)
    assert "Failed to dispatch resolved notification" in caplog.text


def test_reopen_refreezes_baseline_and_writes_audit():
    events = []
    service = IncidentResolutionService(
        dedup=_Recorder("dedup", events),
        correlation=_Recorder("correlation", events),
        entity_recovery=_Recorder("baseline", events),
        drift_cache=_Recorder("drift", events),
        notification_dispatcher=_FailingNotification(),
        audit_logger=_Recorder("audit", events),
        escalation_memory=_Recorder("escalation", events),
    )

    service.reopen("tenant-a", "incident-a", "entity-a", "operator-a")

    assert ("baseline", "tenant-a", "entity-a") in events
    assert any(event[0] == "audit" and event[4] == "incident_reopened" for event in events)
