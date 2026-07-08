"""
tests/unit/phase2/test_schema_validator.py
===============================================
P2-M1  |  Unit tests for SchemaValidator.

Covers: a valid record round-trips correctly; each required-field-missing
case raises SchemaValidationError with a useful message; non-numeric and
non-finite `value` are rejected; timestamps in multiple valid formats
(datetime object, 'Z'-suffixed ISO string, '+00:00'-suffixed ISO string,
tz-naive) are all accepted and normalised to UTC; a genuinely unparseable
timestamp is rejected.
"""
from datetime import datetime, timezone

import pytest

from phase2.ingestion.schema_validator import SchemaValidationError, SchemaValidator
from shared.types import RawRecord


def _valid_event() -> dict:
    return {
        "entity_id": "vm-001",
        "timestamp": "2025-11-11T00:00:00Z",
        "cloud": "AWS",
        "entity_type": "VirtualMachine",
        "namespace": "Compute",
        "metric_name": "cpu_usage",
        "value": 42.5,
    }


class TestValidRecords:
    def test_valid_event_round_trips(self):
        rec = SchemaValidator.validate(_valid_event())
        assert isinstance(rec, RawRecord)
        assert rec.entity_id == "vm-001"
        assert rec.cloud == "AWS"
        assert rec.metric_name == "cpu_usage"
        assert rec.value == 42.5

    def test_timestamp_normalised_to_utc(self):
        rec = SchemaValidator.validate(_valid_event())
        assert rec.timestamp.tzinfo is not None
        assert rec.timestamp.utcoffset().total_seconds() == 0

    def test_accepts_datetime_object_directly(self):
        event = _valid_event()
        event["timestamp"] = datetime(2025, 11, 11, tzinfo=timezone.utc)
        rec = SchemaValidator.validate(event)
        assert rec.timestamp.year == 2025

    def test_accepts_plus_00_00_suffix(self):
        event = _valid_event()
        event["timestamp"] = "2025-11-11T00:00:00+00:00"
        rec = SchemaValidator.validate(event)
        assert rec.timestamp.tzinfo is not None

    def test_accepts_tz_naive_timestamp_assumes_utc(self):
        event = _valid_event()
        event["timestamp"] = "2025-11-11T00:00:00"
        rec = SchemaValidator.validate(event)
        assert rec.timestamp.tzinfo is not None

    def test_value_cast_to_float_from_string(self):
        event = _valid_event()
        event["value"] = "42.5"  # e.g. arrives as a string over the wire
        rec = SchemaValidator.validate(event)
        assert rec.value == 42.5

    def test_all_fields_cast_to_str(self):
        # Defensive: even if upstream sends non-str types for string fields,
        # they should be coerced rather than crashing downstream encoding.
        event = _valid_event()
        event["entity_id"] = 12345
        rec = SchemaValidator.validate(event)
        assert rec.entity_id == "12345"


class TestMissingFields:
    @pytest.mark.parametrize("field", [
        "entity_id", "timestamp", "cloud", "entity_type", "namespace",
        "metric_name", "value",
    ])
    def test_missing_required_field_raises(self, field):
        event = _valid_event()
        del event[field]
        with pytest.raises(SchemaValidationError, match=field):
            SchemaValidator.validate(event)

    def test_none_value_treated_as_missing(self):
        event = _valid_event()
        event["cloud"] = None
        with pytest.raises(SchemaValidationError, match="cloud"):
            SchemaValidator.validate(event)


class TestInvalidValue:
    def test_non_numeric_value_raises(self):
        event = _valid_event()
        event["value"] = "not-a-number"
        with pytest.raises(SchemaValidationError, match="Non-numeric"):
            SchemaValidator.validate(event)

    def test_nan_value_raises(self):
        event = _valid_event()
        event["value"] = float("nan")
        with pytest.raises(SchemaValidationError, match="Non-finite"):
            SchemaValidator.validate(event)

    def test_infinite_value_raises(self):
        event = _valid_event()
        event["value"] = float("inf")
        with pytest.raises(SchemaValidationError, match="Non-finite"):
            SchemaValidator.validate(event)


class TestInvalidTimestamp:
    def test_unparseable_timestamp_raises(self):
        event = _valid_event()
        event["timestamp"] = "not-a-timestamp"
        with pytest.raises(SchemaValidationError, match="Unparseable timestamp"):
            SchemaValidator.validate(event)
