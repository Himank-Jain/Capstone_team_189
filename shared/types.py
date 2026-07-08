"""
shared/types.py
================
CAPSTONE-189  |  Cross-module integration contract.

Scope note
----------
This file currently defines only the dataclasses needed by P2-M1
(Periodic Batch Ingestion) and P2-M2 (Record Encoding). It intentionally
mirrors the EVENT-BASED schema actually produced by generate_corpus.py and
consumed by phase1/data/streaming_aug_pairs_dataset.py — NOT the older
op_id/region-shaped RawRecord sketched in the pre-redesign Directory
Structure doc, which predates the Phase 1 Architecture Addendum.

RawRecord fields map 1:1 onto AUG_REQUIRED_COLS in
streaming_aug_pairs_dataset.py so that a record ingested live and a row
read from aug_pairs.parquet during training go through the identical
encoding path in RecordEncoder.

Extend this file (Severity, AnomalyResult, etc.) as later Phase 2 modules
are built — do not let other modules define their own competing
dataclasses; shared/types.py is the single source of truth (GRASP: Low
Coupling / Indirection).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class RawRecord:
    """
    One (timestamp, metric_name, value) reading EVENT for a single entity.

    This is the event-based shape — one row = one metric reading, not a
    wide row with six fixed metric columns. See the Phase 1 Architecture
    Addendum for why the wide-schema assumption was dropped.

    Parameters
    ----------
    entity_id:
        Unique identifier for the monitored resource.
    timestamp:
        UTC datetime of this reading.
    cloud:
        Cloud provider — AWS | Azure | GCP | OCI | Unknown.
    entity_type:
        Resource category (e.g. "VirtualMachine", "StorageAccount").
    namespace:
        Cloud-native metric namespace the reading belongs to.
    metric_name:
        Which metric this reading is (e.g. "cpu_usage", "Availability").
        Categorical — embedding vocabulary is learned, not hardcoded.
    value:
        Raw numeric reading for metric_name, on that metric's native scale.
    """
    entity_id: str
    timestamp: datetime
    cloud: str
    entity_type: str
    namespace: str
    metric_name: str
    value: float


@dataclass
class EventBatch:
    """
    A time-windowed collection of validated RawRecords, produced by
    BatchAccumulator (P2-M1) and consumed by RecordEncoder (P2-M2).

    Parameters
    ----------
    records:
        Validated records collected during this batch window.
    batch_ts:
        UTC datetime the batch was flushed/closed.
    source:
        Which ingestion adapter produced this batch — kafka | kinesis | pubsub.
    n_invalid:
        Count of events that failed schema validation and were routed to
        the DeadLetterWriter instead of appearing in `records`.
    """
    records: List[RawRecord] = field(default_factory=list)
    batch_ts: datetime = field(default_factory=datetime.utcnow)
    source: str = "unknown"
    n_invalid: int = 0
