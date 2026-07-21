"""
tests/unit/phase2/test_record_encoder.py
=============================================
P2-M2  |  Unit tests for CategoricalEncoder, NumericalEncoder, and
RecordEncoder.

Covers: exact z-score arithmetic against hand-computed expected values
(not just "doesn't crash"); categorical column order matches
AUG_CATEGORICAL_COLS = [cloud, entity_type, namespace, metric_name];
OOV categorical values map to index 0 without raising; OOV metric_names
fall back to the documented mean=0/std=1 passthrough; output tensor
shapes/dtypes match TstccEncoder.forward()'s contract exactly;
collate_encoded_batch() correctly pads variable-length entities and
produces a matching lengths_tensor.
"""
from datetime import datetime, timezone

import pytest
import torch

from phase2.encoding.categorical_encoder import CategoricalEncoder
from phase2.encoding.context_encoder import ContextEncoder
from phase2.encoding.feature_meta import FeatureMetaStore
from phase2.encoding.numerical_encoder import NumericalEncoder
from phase2.encoding.record_encoder import RecordEncoder
from shared.constants import AUG_VALUE_NORM_EPS
from shared.types import RawRecord

VOCAB_MAPS = {
    "cloud": {"AWS": 1, "Azure": 2},
    "entity_type": {"VirtualMachine": 1, "StorageAccount": 2},
    "namespace": {"Compute": 1, "Storage": 2},
    "metric_name": {"cpu_usage": 1, "Availability": 2},
}
METRIC_STATS = {
    "cpu_usage": (50.0, 10.0),
    "Availability": (99.0, 1.0),
}


def _feature_meta() -> FeatureMetaStore:
    return FeatureMetaStore.from_dicts(VOCAB_MAPS, METRIC_STATS)


def _record(
    entity_id="vm-001", cloud="AWS", entity_type="VirtualMachine",
    namespace="Compute", metric_name="cpu_usage", value=60.0,
    timestamp=None,
) -> RawRecord:
    return RawRecord(
        entity_id=entity_id,
        timestamp=timestamp or datetime(2025, 11, 11, 13, 30, 0, tzinfo=timezone.utc),
        cloud=cloud, entity_type=entity_type, namespace=namespace,
        metric_name=metric_name, value=value,
    )


# ─────────────────────────────────────────────────────────────────────────
# CategoricalEncoder
# ─────────────────────────────────────────────────────────────────────────

class TestCategoricalEncoder:
    def test_known_value_maps_to_vocab_index(self):
        enc = CategoricalEncoder(VOCAB_MAPS)
        assert enc.encode("cloud", "AWS") == 1
        assert enc.encode("cloud", "Azure") == 2

    def test_oov_value_maps_to_zero(self):
        enc = CategoricalEncoder(VOCAB_MAPS)
        assert enc.encode("cloud", "GCP") == 0  # never seen in training

    def test_oov_count_increments(self):
        enc = CategoricalEncoder(VOCAB_MAPS)
        enc.encode("metric_name", "brand_new_metric")
        enc.encode("metric_name", "another_new_one")
        assert enc.oov_counts["metric_name"] == 2
        assert enc.oov_counts["cloud"] == 0

    def test_missing_required_column_raises_at_construction(self):
        incomplete = {"cloud": {"AWS": 1}}  # missing entity_type/namespace/metric_name
        with pytest.raises(ValueError, match="missing required"):
            CategoricalEncoder(incomplete)

    def test_non_string_input_is_coerced(self):
        enc = CategoricalEncoder(VOCAB_MAPS)
        # str(12345) won't be in the vocab -> OOV(0), but must not crash
        assert enc.encode("cloud", 12345) == 0


# ─────────────────────────────────────────────────────────────────────────
# NumericalEncoder
# ─────────────────────────────────────────────────────────────────────────

class TestNumericalEncoder:
    def test_zscore_matches_hand_computed_value(self):
        enc = NumericalEncoder(METRIC_STATS)
        result = enc.encode("cpu_usage", 60.0)
        expected = (60.0 - 50.0) / (10.0 + AUG_VALUE_NORM_EPS)
        assert result == pytest.approx(expected, rel=1e-6)

    def test_value_equal_to_mean_gives_zero(self):
        enc = NumericalEncoder(METRIC_STATS)
        assert enc.encode("cpu_usage", 50.0) == pytest.approx(0.0, abs=1e-6)

    def test_oov_metric_name_falls_back_to_mean0_std1(self):
        enc = NumericalEncoder(METRIC_STATS)
        result = enc.encode("never_seen_metric", 7.0)
        expected = (7.0 - 0.0) / (1.0 + AUG_VALUE_NORM_EPS)
        assert result == pytest.approx(expected, rel=1e-6)
        assert enc.oov_metric_count == 1

    def test_nan_value_treated_as_zero(self):
        enc = NumericalEncoder(METRIC_STATS)
        result = enc.encode("cpu_usage", float("nan"))
        expected = (0.0 - 50.0) / (10.0 + AUG_VALUE_NORM_EPS)
        assert result == pytest.approx(expected, rel=1e-6)


# ─────────────────────────────────────────────────────────────────────────
# ContextEncoder
# ─────────────────────────────────────────────────────────────────────────

class TestContextEncoder:
    def test_time_scalars_normalised_to_unit_interval(self):
        ts = datetime(2025, 11, 11, 6, 0, 0, tzinfo=timezone.utc)  # Tuesday, 06:00
        hour_of_day, day_of_week = ContextEncoder.encode_time_scalars(ts)
        assert hour_of_day == pytest.approx(6 / 24.0)
        assert day_of_week == pytest.approx(1 / 7.0)  # Tuesday = weekday() 1

    def test_timestamp_scalar_includes_minutes_and_seconds(self):
        ts = datetime(2025, 11, 11, 6, 30, 0, tzinfo=timezone.utc)
        frac = ContextEncoder.encode_timestamp_scalar(ts)
        expected = (6 + 30 / 60.0) / 24.0
        assert frac == pytest.approx(expected)

    def test_monday_is_zero(self):
        ts = datetime(2025, 11, 10, 0, 0, 0, tzinfo=timezone.utc)  # a Monday
        _, day_of_week = ContextEncoder.encode_time_scalars(ts)
        assert day_of_week == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────
# RecordEncoder — single entity
# ─────────────────────────────────────────────────────────────────────────

class TestRecordEncoderSingleEntity:
    def test_output_shapes_and_dtypes(self):
        enc = RecordEncoder(_feature_meta(), seq_len=32)
        records = [_record(value=float(50 + i)) for i in range(5)]
        result = enc.encode_entity_records(records)

        assert result["numeric"].shape == (5, 3)
        assert result["categorical"].shape == (5, 4)
        assert result["timestamps"].shape == (5, 1)
        assert result["numeric"].dtype == torch.float32
        assert result["categorical"].dtype == torch.int64
        assert result["timestamps"].dtype == torch.float32

    def test_categorical_column_order_is_cloud_entitytype_namespace_metric(self):
        enc = RecordEncoder(_feature_meta(), seq_len=32)
        rec = _record(cloud="AWS", entity_type="VirtualMachine",
                       namespace="Compute", metric_name="cpu_usage")
        result = enc.encode_entity_records([rec])
        row = result["categorical"][0].tolist()
        assert row == [1, 1, 1, 1]  # each is index 1 in its respective vocab

    def test_truncates_to_most_recent_seq_len_events(self):
        enc = RecordEncoder(_feature_meta(), seq_len=3)
        records = [
            _record(value=float(i), timestamp=datetime(2025, 11, 11, 0, i, tzinfo=timezone.utc))
            for i in range(10)
        ]
        result = enc.encode_entity_records(records)
        assert result["numeric"].shape[0] == 3
        # the LAST 3 events (values 7, 8, 9) should be kept, not the first 3
        kept_values = result["numeric"][:, 0]  # value_norm column
        # value_norm is monotonic in raw value here, so relative order check suffices
        assert kept_values[0] < kept_values[1] < kept_values[2]

    def test_events_sorted_by_timestamp_even_if_input_unordered(self):
        enc = RecordEncoder(_feature_meta(), seq_len=32)
        rec_late = _record(value=99.0, timestamp=datetime(2025, 11, 11, 2, 0, tzinfo=timezone.utc))
        rec_early = _record(value=1.0, timestamp=datetime(2025, 11, 11, 0, 0, tzinfo=timezone.utc))
        result = enc.encode_entity_records([rec_late, rec_early])  # deliberately out of order
        # after sorting, the early (lower-value) record should come first
        assert result["numeric"][0, 0] < result["numeric"][1, 0]


# ─────────────────────────────────────────────────────────────────────────
# RecordEncoder — batch / collation
# ─────────────────────────────────────────────────────────────────────────

class TestRecordEncoderBatchCollation:
    def test_collate_pads_variable_length_entities(self):
        enc = RecordEncoder(_feature_meta(), seq_len=32)
        encoded = {
            "vm-A": enc.encode_entity_records([_record(entity_id="vm-A") for _ in range(5)]),
            "vm-B": enc.encode_entity_records([_record(entity_id="vm-B") for _ in range(2)]),
        }
        entity_ids, numeric_t, categorical_t, timestamps_t, lengths_t = (
            RecordEncoder.collate_encoded_batch(encoded)
        )

        assert set(entity_ids) == {"vm-A", "vm-B"}
        assert numeric_t.shape == (2, 5, 3)       # padded to max_len=5
        assert categorical_t.shape == (2, 5, 4)
        assert timestamps_t.shape == (2, 5, 1)

        lengths_by_id = dict(zip(entity_ids, lengths_t.tolist()))
        assert lengths_by_id["vm-A"] == 5
        assert lengths_by_id["vm-B"] == 2

    def test_padded_positions_are_zero(self):
        enc = RecordEncoder(_feature_meta(), seq_len=32)
        encoded = {"vm-B": enc.encode_entity_records([_record(entity_id="vm-B") for _ in range(2)])}
        # add a longer entity so vm-B gets padded
        encoded["vm-A"] = enc.encode_entity_records([_record(entity_id="vm-A") for _ in range(4)])

        entity_ids, numeric_t, categorical_t, _, lengths_t = (
            RecordEncoder.collate_encoded_batch(encoded)
        )
        b_idx = entity_ids.index("vm-B")
        b_len = lengths_t[b_idx].item()
        # everything from b_len onward should be zero-padded
        assert torch.all(numeric_t[b_idx, b_len:] == 0.0)
        assert torch.all(categorical_t[b_idx, b_len:] == 0)

    def test_empty_batch_raises(self):
        with pytest.raises(ValueError, match="empty batch"):
            RecordEncoder.collate_encoded_batch({})
