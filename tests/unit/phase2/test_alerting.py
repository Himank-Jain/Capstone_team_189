from datetime import datetime, timezone

import fakeredis

from phase2.alerting.alert_deduplicator import AlertDeduplicator
from phase2.alerting.correlation_engine import (
    BaseEntityAttributesProvider,
    CorrelationEngine,
)
from shared.types import (
    AnomalyResult,
    EntityAttributesData,
    GroupType,
    Severity,
)


class InMemoryAttributesProvider(BaseEntityAttributesProvider):
    def __init__(self, attributes):
        self._attributes = attributes

    def get_attributes(self, entity_id: str) -> EntityAttributesData:
        return self._attributes[entity_id]


def make_anomaly(entity_id: str, batch_ts: datetime) -> AnomalyResult:
    return AnomalyResult(
        entity_id=entity_id,
        final_score=0.75,
        severity=Severity.HIGH,
        deviation_contribution=0.3,
        drift_contribution=0.3,
        similarity_contribution=0.15,
        batch_ts=batch_ts,
    )


def test_alert_deduplicator_reuses_incident_and_increments_recurrence():
    redis_client = fakeredis.FakeStrictRedis()
    deduplicator = AlertDeduplicator(redis_client)
    batch_ts = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)

    first_result = deduplicator.check(make_anomaly("entity-1", batch_ts))
    duplicate_result = deduplicator.check(make_anomaly("entity-1", batch_ts))

    assert first_result.is_duplicate is False
    assert duplicate_result.is_duplicate is True
    assert duplicate_result.canonical_incident_id == first_result.canonical_incident_id
    assert duplicate_result.recurrence_count == 2


def test_correlation_engine_groups_entities_sharing_two_attributes():
    provider = InMemoryAttributesProvider(
        {
            "entity-1": EntityAttributesData("entity-1", "AWS", "us-east-1", "op-1"),
            "entity-2": EntityAttributesData("entity-2", "AWS", "us-east-1", "op-2"),
        }
    )
    engine = CorrelationEngine(provider)
    first_ts = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    second_ts = datetime(2026, 7, 23, 12, 5, tzinfo=timezone.utc)

    first_result = engine.process("entity-1", "incident-1", first_ts)
    second_result = engine.process("entity-2", "incident-2", second_ts)

    assert first_result.group_type is GroupType.ISOLATED
    assert second_result.group_type is GroupType.CORRELATED
    assert second_result.group_size == 2
    assert second_result.related_ids == ["incident-1"]
