"""
phase2/encoding/context_encoder.py
======================================
P2-M2  |  ContextEncoder — derives the two time-scalar numeric features
(hour_of_day, day_of_week) AND the separate Time2Vec input scalar from a
raw timestamp. These are two DIFFERENT derivations feeding two different
places in TstccEncoder — do not conflate them:

1. hour_of_day / day_of_week  → part of the 3 numeric features
   (AUG_NUMERIC_COLS = [value_norm, hour_of_day, day_of_week]), fed
   through EmbeddingLayer's numeric Linear→LayerNorm path.
   Matches generate_corpus.py / streaming_aug_pairs_dataset.py exactly:
     hour_of_day_raw = ts.hour                 (int, 0–23)
     day_of_week_raw = ts.dayofweek             (int, 0=Monday .. 6=Sunday)
     hour_of_day = hour_of_day_raw / 24.0
     day_of_week = day_of_week_raw / 7.0

2. timestamps_tensor  → fed separately into TstccEncoder's own Time2Vec
   module, NOT part of the 3 numeric features. Matches
   _rows_to_seq_dict() exactly:
     frac_hour = (ts.hour + ts.minute/60 + ts.second/3600) / 24.0

Python's datetime.weekday() uses the same Monday=0..Sunday=6 convention
as pandas' Timestamp.dayofweek, so deriving directly from a live
datetime (rather than a precomputed column) stays consistent with the
training-time corpus.
"""

from __future__ import annotations

from datetime import datetime
from typing import Tuple


class ContextEncoder:
    """Stateless — timestamp derivations only, no learned parameters."""

    @staticmethod
    def encode_time_scalars(ts: datetime) -> Tuple[float, float]:
        """Returns (hour_of_day, day_of_week), each normalised to [0, 1)."""
        hour_of_day = ts.hour / 24.0
        day_of_week = ts.weekday() / 7.0  # Monday=0 .. Sunday=6, matches pandas dayofweek
        return hour_of_day, day_of_week

    @staticmethod
    def encode_timestamp_scalar(ts: datetime) -> float:
        """Fractional-hour-of-day in [0, 1), fed to TstccEncoder's Time2Vec
        module. Distinct from encode_time_scalars()'s coarser hour_of_day."""
        frac_hour = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
        return frac_hour / 24.0
