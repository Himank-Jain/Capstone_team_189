"""Metric attribution: ranking, direction, thresholds, determinism, Phase 0 lookup."""
from datetime import datetime, timedelta, timezone

from demo_generator.generator import DemoGenerator
from phase0.baseline.in_memory_store import InMemoryRollingBaselineStore
from phase0.bucketing.bucket_key_resolver import BucketKeyResolver
from phase3.rca.metric_attribution import (
    ConstantBaselineLookup,
    MetricAttributor,
    Phase0BaselineLookup,
)
from shared.types import RawRecord

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _rec(metric, value, i=0, entity="e"):
    return RawRecord(entity, T0 + timedelta(minutes=i), "AWS", "VirtualMachine", "ns", metric, value)


VOCAB = ["cpu_usage", "network_out_bytes", "request_count", "disk_read_ops"]


def test_ranks_metrics_and_sets_direction():
    attr = MetricAttributor(VOCAB)
    observed = [_rec("cpu_usage", 400, i) for i in range(5)] + [_rec("request_count", 100, i) for i in range(5)]
    res = attr.attribute(observed, ConstantBaselineLookup(100.0, 2.0))
    assert res.contributions[0].metric_name == "cpu_usage"
    assert res.contributions[0].direction == "increase"
    assert res.contributions[0].contribution == 150.0
    assert "metric_family:cpu_utilization" in res.contributing_features
    assert res.metric_directions["cpu_utilization"] == "increase"


def test_unchanged_metric_is_not_a_feature():
    attr = MetricAttributor(VOCAB)
    res = attr.attribute([_rec("cpu_usage", 101, i) for i in range(5)], ConstantBaselineLookup())
    assert res.contributing_features == []


def test_decrease_direction():
    attr = MetricAttributor(VOCAB)
    res = attr.attribute([_rec("request_count", 10, i) for i in range(5)], ConstantBaselineLookup())
    assert res.metric_directions
    assert set(res.metric_directions.values()) == {"decrease"}


def test_deterministic_and_order_independent():
    attr = MetricAttributor(VOCAB)
    observed = [_rec("cpu_usage", 300, i) for i in range(4)] + [_rec("request_count", 250, i) for i in range(4)]
    a = attr.attribute(observed, ConstantBaselineLookup())
    b = attr.attribute(list(reversed(observed)), ConstantBaselineLookup())
    assert a == b


def test_metric_without_baseline_is_reported_not_guessed():
    attr = MetricAttributor(VOCAB)
    res = attr.attribute([_rec("cpu_usage", 500)], lambda rec: None)
    assert res.unscored_metrics == ["cpu_usage"] and res.contributing_features == []


def test_phase0_lookup_uses_the_stored_baseline():
    store = InMemoryRollingBaselineStore(window_size=30)
    resolver = BucketKeyResolver()
    for day in range(20):
        ts = T0 + timedelta(days=day)
        store.update_bucket(resolver.resolve("e", "cpu_usage", ts), 40.0 + (day % 3))
    lookup = Phase0BaselineLookup(store, resolver)
    expected, scale = lookup(_rec("cpu_usage", 0, 0))
    assert 39 < expected < 43 and scale > 0
    attr = MetricAttributor(VOCAB)
    res = attr.attribute([_rec("cpu_usage", 90, i) for i in range(3)], lookup)
    assert res.metric_directions["cpu_utilization"] == "increase"


def test_vocabulary_from_demo_generator_resolves_families():
    gen = DemoGenerator()
    attr = MetricAttributor(gen.metric_vocabulary)
    assert any(attr.families_of(m) for m in gen.metric_vocabulary)


def test_step_and_spike_shapes_are_not_averaged_away():
    attr = MetricAttributor(VOCAB)
    step = [_rec("cpu_usage", 100 if i < 16 else 300, i) for i in range(32)]
    spike = [_rec("request_count", 100 if i < 29 else 400, i) for i in range(32)]
    res = attr.attribute(step + spike, ConstantBaselineLookup())
    assert res.metric_directions["cpu_utilization"] == "increase"
    assert res.metric_directions["request_count"] == "increase"


def test_single_stray_reading_is_ignored():
    attr = MetricAttributor(VOCAB)
    values = [100] * 31 + [900]
    res = attr.attribute([_rec("cpu_usage", v, i) for i, v in enumerate(values)], ConstantBaselineLookup())
    assert res.contributing_features == []
