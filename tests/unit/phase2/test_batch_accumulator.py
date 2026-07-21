"""
tests/unit/phase2/test_batch_accumulator.py
================================================
P2-M1  |  Unit tests for BatchAccumulator.

Covers: records accumulate across add() calls; flush() returns an
EventBatch containing exactly what was added, then resets the buffer;
should_flush() reflects elapsed time against window_seconds; an empty
accumulator (no records, no invalid) flushes to None; n_invalid is
carried onto the EventBatch and reset after flush; source label is
preserved.
"""
import time
from datetime import datetime, timezone

from phase2.ingestion.batch_accumulator import BatchAccumulator
from shared.types import RawRecord


def _record(entity_id: str = "vm-001") -> RawRecord:
    return RawRecord(
        entity_id=entity_id,
        timestamp=datetime.now(timezone.utc),
        cloud="AWS",
        entity_type="VirtualMachine",
        namespace="Compute",
        metric_name="cpu_usage",
        value=1.0,
    )


class TestAccumulateAndFlush:
    def test_added_records_appear_in_flushed_batch(self):
        acc = BatchAccumulator(window_seconds=9999, source="test")
        acc.add(_record("a"))
        acc.add(_record("b"))

        batch = acc.flush()

        assert batch is not None
        assert len(batch.records) == 2
        assert {r.entity_id for r in batch.records} == {"a", "b"}

    def test_source_label_preserved_on_batch(self):
        acc = BatchAccumulator(window_seconds=9999, source="kafka")
        acc.add(_record())
        batch = acc.flush()
        assert batch.source == "kafka"

    def test_flush_resets_buffer(self):
        acc = BatchAccumulator(window_seconds=9999, source="test")
        acc.add(_record())
        first = acc.flush()
        second = acc.flush()  # nothing added since first flush

        assert first is not None
        assert len(first.records) == 1
        assert second is None  # empty buffer + no invalid -> None

    def test_flush_with_no_records_and_no_invalid_returns_none(self):
        acc = BatchAccumulator(window_seconds=9999, source="test")
        assert acc.flush() is None


class TestInvalidCountTracking:
    def test_mark_invalid_carried_onto_batch(self):
        acc = BatchAccumulator(window_seconds=9999, source="test")
        acc.add(_record())
        acc.mark_invalid(3)

        batch = acc.flush()

        assert batch.n_invalid == 3
        assert len(batch.records) == 1

    def test_invalid_count_resets_after_flush(self):
        acc = BatchAccumulator(window_seconds=9999, source="test")
        acc.mark_invalid(2)
        first = acc.flush()
        acc.mark_invalid(1)
        second = acc.flush()

        assert first.n_invalid == 2
        assert second.n_invalid == 1  # not 3 — must not carry over

    def test_only_invalid_events_still_produces_a_batch(self):
        # No valid records at all this window, but invalid events did
        # occur — this is still worth flushing (n_invalid > 0), unlike
        # a truly empty window which returns None.
        acc = BatchAccumulator(window_seconds=9999, source="test")
        acc.mark_invalid(5)
        batch = acc.flush()

        assert batch is not None
        assert batch.records == []
        assert batch.n_invalid == 5


class TestShouldFlushTiming:
    def test_should_flush_false_immediately_after_construction(self):
        acc = BatchAccumulator(window_seconds=9999, source="test")
        assert acc.should_flush() is False

    def test_should_flush_true_after_window_elapses(self):
        acc = BatchAccumulator(window_seconds=0.05, source="test")
        assert acc.should_flush() is False
        time.sleep(0.08)
        assert acc.should_flush() is True

    def test_flush_resets_the_window_timer(self):
        acc = BatchAccumulator(window_seconds=0.05, source="test")
        time.sleep(0.08)
        assert acc.should_flush() is True
        acc.add(_record())
        acc.flush()
        assert acc.should_flush() is False  # timer restarted by flush()
