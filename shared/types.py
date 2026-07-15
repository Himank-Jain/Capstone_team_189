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

import numpy as np


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


@dataclass
class EntityProfile:
    """
    Per-entity behavioral baseline, written by ReferenceEncoderService
    (P2-M4) and read by CosineDeviationScorer (P2-M7) / MmdDriftMonitor
    (P2-M8) via EntityStoreReader. This is the P2-M6 store's payload shape
    for one entity — see Directory Structure Addendum Section 5.

    Parameters
    ----------
    entity_id:
        Unique identifier for the monitored resource.
    centroid_emb:
        Shape (128,), L2-normalised. Mean of the last `n_records` window
        embeddings (or updated incrementally via EMA — see
        REF_CENTROID_ALPHA in shared/constants.py).
    history_embs:
        Up to REDIS_HISTORY_LEN most recent window embeddings, each
        shape (128,), L2-normalised, chronological (oldest first).
    emb_variance:
        Scalar spread measure — trace of the covariance matrix of
        history_embs. Higher = more behaviorally volatile entity.
    n_records:
        Count of window-embeddings that contributed to centroid_emb
        (NOT raw event count). Distinct from len(history_embs) once
        history_embs is capped at REDIS_HISTORY_LEN.
    last_update_ts:
        UTC datetime this profile was last written or EMA-updated.
    cold_start_flag:
        True when this entity had no (or insufficient) history and
        centroid_emb was seeded from the global mean instead of the
        entity's own data.
    """
    entity_id: str
    centroid_emb: np.ndarray
    history_embs: List[np.ndarray]
    emb_variance: float
    n_records: int
    last_update_ts: datetime
    cold_start_flag: bool = False


@dataclass
class CurrentEmbedding:
    """
    One entity's "current behavior fingerprint" for a single ingestion
    batch — output of CurrentEmbeddingAggregator (P2-M5), written to the
    entity store's current_embedding field and consumed directly by
    CosineDeviationScorer (P2-M7).

    Field names here are the canonical contract from the Directory
    Structure Addendum, Section 5 (`emb` / `batch_ts` / `n_records`) —
    NOT the `embedding` / `batch_timestamp` / `record_count` names used
    in the P2-M5 planner prose, which predate this file. Do not rename
    without a team PR (this file is frozen per its own module docstring).

    Parameters
    ----------
    entity_id:
        Unique identifier for the monitored resource.
    emb:
        Shape (128,), L2-normalised. Mean-pooled across every window
        embedding this entity produced within the batch, normalised
        AFTER pooling (not before — see CurrentEmbeddingAggregator).
    batch_ts:
        UTC datetime of the ingestion batch this embedding summarises.
    n_records:
        Count of window-embeddings that were pooled into `emb` for this
        entity in this batch (1 if the entity appeared only once).
    cloud_provider:
        AWS | Azure | GCP | OCI — carried through from the entity's
        RawRecords for downstream filtering/dashboarding.
    """
    entity_id: str
    emb: np.ndarray
    batch_ts: datetime
    n_records: int
    cloud_provider: str
