"""
phase2/encoding/record_encoder.py
=====================================
P2-M2  |  RecordEncoder â€” turns validated RawRecords into the exact raw
tensors TstccEncoder.forward() expects. Does NOT own nn.Embedding tables
or Time2Vec â€” those already exist, trained, inside the loaded TstccEncoder
checkpoint (see EmbeddingLayer / Time2Vec in phase1/models/tstcc_encoder.py).
Duplicating them here would create a second, untrained embedding space
disconnected from the checkpoint and silently corrupt every embedding.

Output contract (must match TstccEncoder.forward() positionally)
------------------------------------------------------------------
    numeric_input_tensor      : (batch, seq_len, 3)   float32
                                 [value_norm, hour_of_day, day_of_week]
    categorical_input_tensor  : (batch, seq_len, 4)   int64 vocab indices
                                 [cloud, entity_type, namespace, metric_name]
    timestamps_tensor         : (batch, seq_len, 1)   float32
                                 fractional-hour-of-day in [0, 1)
    lengths_tensor            : (batch,)               int64, true length
                                 per entity before padding (variable-length
                                 sequence support â€” see TstccEncoder._run_gru)

Windowing note
--------------
Training windows are `seq_len` consecutive reading EVENTS per entity
(interleaved across whatever metrics that entity emits), not distinct
timesteps. At inference, one EventBatch per entity rarely lines up to an
exact seq_len â€” RecordEncoder takes the most recent `seq_len` events per
entity (or all of them if fewer are available) and relies on
TstccEncoder's lengths_tensor support for entities with short histories,
exactly mirroring how training already handles variable per-entity row
counts within a row group.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import torch

from phase2.encoding.categorical_encoder import CategoricalEncoder
from phase2.encoding.context_encoder import ContextEncoder
from phase2.encoding.feature_meta import FeatureMetaStore
from phase2.encoding.numerical_encoder import NumericalEncoder
from shared.constants import AUG_PAIRS_CATEGORICAL_COLS as AUG_CATEGORICAL_COLS
from shared.types import EventBatch, RawRecord

logger_obj = logging.getLogger(__name__)

DEFAULT_SEQ_LEN: int = 32  # matches train_tstcc.py's --seq-len default


class RecordEncoder:
    """
    Parameters
    ----------
    feature_meta:
        FeatureMetaStore holding the SAME vocab maps / per-metric stats
        used to train the TstccEncoder checkpoint this feeds. Never
        construct this class with independently re-derived vocab/stats.
    seq_len:
        Max events per entity per window. Entities with fewer available
        events are passed through at their true (shorter) length via
        lengths_tensor rather than zero-padded to look like real data.
    """

    def __init__(self, feature_meta: FeatureMetaStore, seq_len: int = DEFAULT_SEQ_LEN) -> None:
        self._seq_len = seq_len
        self._categorical_encoder = CategoricalEncoder(feature_meta.vocab_maps_dict)
        self._numerical_encoder = NumericalEncoder(feature_meta.metric_value_stats_dict)
        self._context_encoder = ContextEncoder()

    # â”€â”€ Single-entity encoding â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def encode_entity_records(
        self, records: List[RawRecord]
    ) -> Dict[str, torch.Tensor]:
        """
        Encode one entity's chronologically-ordered records into the three
        raw tensors TstccEncoder expects for a single (unbatched) sequence.

        Parameters
        ----------
        records:
            All belonging to ONE entity_id. Sorted here by
            (timestamp, metric_name) â€” same stable tiebreaker training
            uses, since multiple metrics can share a timestamp in
            event-based format. Truncated to the most recent `seq_len`
            events if longer.

        Returns
        -------
        dict with keys "numeric" (seq_len, 3), "categorical" (seq_len, 4),
        "timestamps" (seq_len, 1) â€” mirrors
        streaming_aug_pairs_dataset.py's _rows_to_seq_dict() shape exactly.
        """
        ordered = sorted(records, key=lambda r: (r.timestamp, r.metric_name))
        if len(ordered) > self._seq_len:
            ordered = ordered[-self._seq_len:]  # most recent seq_len events

        numeric_rows: List[List[float]] = []
        categorical_rows: List[List[int]] = []
        timestamp_rows: List[List[float]] = []

        for rec in ordered:
            value_norm = self._numerical_encoder.encode(rec.metric_name, rec.value)
            hour_of_day, day_of_week = self._context_encoder.encode_time_scalars(rec.timestamp)
            numeric_rows.append([value_norm, hour_of_day, day_of_week])

            cat_row = [
                self._categorical_encoder.encode("cloud", rec.cloud),
                self._categorical_encoder.encode("entity_type", rec.entity_type),
                self._categorical_encoder.encode("namespace", rec.namespace),
                self._categorical_encoder.encode("metric_name", rec.metric_name),
            ]
            categorical_rows.append(cat_row)

            timestamp_rows.append([self._context_encoder.encode_timestamp_scalar(rec.timestamp)])

        return {
            "numeric": torch.tensor(numeric_rows, dtype=torch.float32),
            "categorical": torch.tensor(categorical_rows, dtype=torch.int64),
            "timestamps": torch.tensor(timestamp_rows, dtype=torch.float32),
        }

    # â”€â”€ Batch encoding â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def encode_event_batch(
        self, batch: EventBatch
    ) -> Dict[str, Dict[str, torch.Tensor]]:
        """
        Group an EventBatch's records by entity_id and encode each entity's
        sequence independently.

        Returns
        -------
        {entity_id: {"numeric": ..., "categorical": ..., "timestamps": ...}}
        Per-entity tensors are NOT padded to a common length here â€” use
        collate_encoded_batch() to stack them for a single TstccEncoder
        forward() call with a lengths_tensor.
        """
        by_entity: Dict[str, List[RawRecord]] = defaultdict(list)
        for rec in batch.records:
            by_entity[rec.entity_id].append(rec)

        return {
            entity_id: self.encode_entity_records(records)
            for entity_id, records in by_entity.items()
        }

    @staticmethod
    def collate_encoded_batch(
        encoded_by_entity: Dict[str, Dict[str, torch.Tensor]],
    ) -> Tuple[List[str], torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Zero-pad a variable-length per-entity encoding dict into a single
        batch, ready to pass directly to TstccEncoder.forward().

        Returns
        -------
        (entity_ids, numeric_tensor, categorical_tensor, timestamps_tensor, lengths_tensor)
            numeric_tensor     : (batch, max_seq_len, 3)
            categorical_tensor : (batch, max_seq_len, 4)  â€” pad value 0 (PAD/UNK)
            timestamps_tensor  : (batch, max_seq_len, 1)
            lengths_tensor     : (batch,) int64 â€” true length per entity,
                                 pass directly as TstccEncoder's lengths_tensor
                                 arg so padded positions are masked out.
        """
        entity_ids = list(encoded_by_entity.keys())
        if not entity_ids:
            raise ValueError("[RecordEncoder] Cannot collate an empty batch")

        lengths = [encoded_by_entity[eid]["numeric"].shape[0] for eid in entity_ids]
        max_len = max(lengths)
        num_categorical_cols = len(AUG_CATEGORICAL_COLS)

        numeric_batch = torch.zeros(len(entity_ids), max_len, 3, dtype=torch.float32)
        categorical_batch = torch.zeros(len(entity_ids), max_len, num_categorical_cols, dtype=torch.int64)
        timestamps_batch = torch.zeros(len(entity_ids), max_len, 1, dtype=torch.float32)

        for i, eid in enumerate(entity_ids):
            seq_len_i = lengths[i]
            numeric_batch[i, :seq_len_i] = encoded_by_entity[eid]["numeric"]
            categorical_batch[i, :seq_len_i] = encoded_by_entity[eid]["categorical"]
            timestamps_batch[i, :seq_len_i] = encoded_by_entity[eid]["timestamps"]

        lengths_tensor = torch.tensor(lengths, dtype=torch.int64)
        return entity_ids, numeric_batch, categorical_batch, timestamps_batch, lengths_tensor
