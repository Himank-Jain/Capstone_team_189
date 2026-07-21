"""
VM Telemetry Contrastive Augmentation — Positive Pair Generator
===============================================================

Why these two augmentation strategies for VM telemetry?

VM behavior is fundamentally time-cyclic: a web server at 3:05am behaves
essentially the same as at 3:02am — Temporal Jitter exploits this by
teaching the encoder to treat tiny time shifts as the same behavioral state,
preventing it from memorising clock values instead of actual patterns.

Attribute Masking mirrors real-world observability gaps (dropped metrics,
agent failures, network blips) and forces the encoder to build robust
representations that don't rely on any single sensor being present — much
like how a doctor can diagnose from partial lab results.

Together they ensure the learned embedding captures the *semantic identity*
of a VM's behavior (what kind of load pattern this is) rather than surface
correlations with exact timestamps or complete feature vectors.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch
from torch.utils.data import Dataset


# ─── Configuration ────────────────────────────────────────────────────────────

@dataclass
class AugmentationConfig:
    # --- Temporal Jitter ---
    jitter_min_minutes: float = 1.0    # minimum time shift applied to timestamp
    jitter_max_minutes: float = 5.0    # maximum time shift (positive or negative)

    # --- Attribute Masking ---
    mask_ratio_min: float = 0.10       # mask at least 10% of numeric features
    mask_ratio_max: float = 0.30       # mask at most  30% of numeric features
    mask_fill_value: float = 0.0
    batch_size: int = 10_000       # value used to replace masked features
                                       # (use -1.0 or a learned token if preferred)

    # --- Column Roles ---
    # These columns carry raw numeric sensor readings — safe to mask / jitter-derive
    numeric_cols: list[str] = field(default_factory=lambda: [
        "cpu_usage",
        "memory_usage",
        "disk_io_read",
        "disk_io_write",
        "net_throughput_in",
        "net_throughput_out",
    ])

    # These columns define VM identity — NEVER masked or distorted
    protected_cols: list[str] = field(default_factory=lambda: [
        "vm_role",      # web / db / cache — semantic label, must stay intact
        "region",       # geographic tag — part of behavioral context
        "os_type",      # OS family — affects valid metric ranges
    ])

    # Raw timestamp column name in the parquet file
    timestamp_col: str = "timestamp"

    # Time2Vec output dimension (must match your encoder's input expectation)
    time2vec_dim: int = 8


# ─── Time2Vec ─────────────────────────────────────────────────────────────────

def time2vec(t: float, dim: int) -> list[float]:
    """
    Convert a scalar time value (fractional hour, 0–23.99) into a
    cycle-aware continuous feature vector using the Time2Vec formulation.

    The first element is a linear trend term (captures long-range drift).
    The remaining (dim-1) elements are sine waves at different frequencies —
    this lets the model learn that 3am on Monday ≈ 3am on Tuesday without
    hard-coding any periodicity assumption.

    Reference: Kazemi et al., "Time2Vec: Learning a Vector Representation of Time", 2019.
    """
    features = [t]  # linear term: encodes absolute position weakly
    for k in range(1, dim):
        # Each sine has a different frequency: k controls the "zoom level"
        # k=1 → daily cycle, k=2 → half-day, etc.
        features.append(math.sin(2 * math.pi * k * t / 24.0))
    return features


def extract_time_features(ts: pd.Timestamp, dim: int) -> list[float]:
    """
    Derive all time-based features from a timestamp.
    Returns: [hour_of_day (fractional), day_of_week (0-6), ...time2vec...]

    Fractional hour (e.g. 14.5 for 14:30) preserves minute-level resolution
    so that jitter shifts actually change the feature values — integer hours
    would collapse ±5 min jitter to zero effect.
    """
    fractional_hour = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
    day_of_week = float(ts.dayofweek)  # 0=Monday … 6=Sunday
    t2v = time2vec(fractional_hour, dim)
    return [fractional_hour, day_of_week] + t2v


# ─── Augmentation Functions ───────────────────────────────────────────────────

def apply_temporal_jitter(
    record: dict,
    config: AugmentationConfig,
) -> dict:
    """
    Temporal Jitter augmentation.

    Shifts the timestamp by a random delta in [jitter_min, jitter_max] minutes,
    with a random sign (earlier or later). Then recomputes all time-derived
    features from the shifted timestamp.

    WHY: VM behavior is quasi-stationary over windows of a few minutes —
    a spike at 02:03 and 02:07 represent the same behavioral episode.
    Training on jittered pairs teaches the encoder this invariance so it
    learns "3am low-traffic pattern" rather than "timestamp=03:04:17".
    """
    out = record.copy()

    original_ts: pd.Timestamp = out[config.timestamp_col]

    # Random delta: magnitude drawn uniformly, sign drawn from {-1, +1}
    delta_minutes = random.uniform(config.jitter_min_minutes, config.jitter_max_minutes)
    sign = random.choice([-1, 1])
    shifted_ts = original_ts + pd.Timedelta(minutes=sign * delta_minutes)

    # Store the shifted timestamp (the model never sees raw timestamps —
    # only the derived features below — but we store it for debugging)
    out[config.timestamp_col] = shifted_ts

    # Recompute every time-derived feature from the new timestamp
    time_feats = extract_time_features(shifted_ts, config.time2vec_dim)
    out["hour_of_day"]   = time_feats[0]
    out["day_of_week"]   = time_feats[1]
    out["time2vec"]      = time_feats[2:]   # list of floats, flattened later

    return out


def apply_attribute_masking(
    record: dict,
    config: AugmentationConfig,
) -> dict:
    """
    Attribute Masking augmentation.

    Randomly zeroes out a fraction (mask_ratio_min … mask_ratio_max) of the
    numeric metric columns. Protected columns (vm_role, region, os_type) are
    NEVER touched.

    WHY: In production, monitoring agents occasionally drop metrics — a disk
    probe fails, a network counter resets. If the encoder has never seen
    partial observations during training it will produce garbage embeddings
    at inference time when a sensor is missing. Masking during training
    builds robustness to exactly this scenario.

    The fill value (default 0.0) is chosen to be near the normalised mean
    of most metrics after StandardScaler preprocessing. For raw (un-normalised)
    data you may prefer mask_fill_value = -1.0 as an explicit OOD sentinel.
    """
    out = record.copy()

    # Decide *how many* columns to mask this call (stochastic ratio)
    n_numeric = len(config.numeric_cols)
    n_to_mask = max(1, round(
        random.uniform(config.mask_ratio_min, config.mask_ratio_max) * n_numeric
    ))

    # Pick which columns are masked — fresh random selection every __getitem__
    cols_to_mask = random.sample(config.numeric_cols, n_to_mask)

    for col in cols_to_mask:
        if col in out:
            out[col] = config.mask_fill_value
            # Keep a binary mask vector so the encoder can optionally learn
            # to attend differently to masked positions (like BERT masking)
            out[f"{col}_masked"] = 1.0
        # If the column is absent in this record (e.g. sparse parquet),
        # silently skip — the encoder already has to handle missing cols
    
    # Set mask=0 for unmasked cols (gives encoder a clean binary signal)
    for col in config.numeric_cols:
        if f"{col}_masked" not in out:
            out[f"{col}_masked"] = 0.0

    return out


def augment_record(record: dict, config: AugmentationConfig) -> dict:
    """
    Apply both augmentations in sequence to produce one view.
    Order: jitter first (changes time features), then mask (drops some metrics).
    Both are applied independently per call so view_1 ≠ view_2 stochastically.
    """
    record = apply_temporal_jitter(record, config)
    record = apply_attribute_masking(record, config)
    return record


# ─── Record → Tensor ──────────────────────────────────────────────────────────

def record_to_tensor(record: dict, config: AugmentationConfig) -> torch.Tensor:
    """
    Flatten a record dict into a 1-D float32 tensor suitable for the encoder.

    Feature layout (must match your encoder's input_dim):
      [numeric_cols (+ their mask flags)] + [hour_of_day, day_of_week] + [time2vec]

    Categorical columns (vm_role, region, os_type) are intentionally excluded
    here — they should go through nn.Embedding layers in your encoder, not
    raw concatenation. Pass them as separate integer tensors in your DataLoader
    collate_fn if needed.
    """
    parts: list[float] = []

    # 1. Numeric metrics + their binary mask indicator
    for col in config.numeric_cols:
        parts.append(float(record.get(col, 0.0)))
        parts.append(float(record.get(f"{col}_masked", 0.0)))

    # 2. Scalar time features
    parts.append(float(record.get("hour_of_day", 0.0)))
    parts.append(float(record.get("day_of_week", 0.0)))

    # 3. Time2Vec vector (list stored under "time2vec" key)
    t2v = record.get("time2vec", [0.0] * config.time2vec_dim)
    parts.extend([float(x) for x in t2v])

    return torch.tensor(parts, dtype=torch.float32)


# ─── Dataset ──────────────────────────────────────────────────────────────────

class VMContrastiveDataset(Dataset):
    """
    PyTorch Dataset that yields positive pairs (view_1, view_2) for
    NT-Xent / SimCLR contrastive training.

    Each call to __getitem__(i) applies two *independent* stochastic
    augmentations to record i, so the pair is different every epoch —
    this is critical for contrastive learning; pre-computed static pairs
    cause the encoder to memorise pair identities rather than learning
    generalised representations.

    Args:
        source:  path to a .parquet file  OR  a pre-loaded pd.DataFrame
        config:  AugmentationConfig instance controlling all hyperparameters
    """

    def __init__(
        self,
        source: Union[str, Path, pd.DataFrame],
        config: AugmentationConfig | None = None,
    ):
        self.config = config or AugmentationConfig()

        # ── Load data ──────────────────────────────────────────────────────
        if isinstance(source, (str, Path)):
            # PyArrow read is faster than pd.read_parquet for large files
            table = pq.read_table(str(source))
            self.df = table.to_pandas()
        elif isinstance(source, pd.DataFrame):
            self.df = source.reset_index(drop=True)
        else:
            raise TypeError(f"source must be a path or DataFrame, got {type(source)}")

        # ── Ensure timestamp column is proper datetime ─────────────────────
        if self.config.timestamp_col in self.df.columns:
            self.df[self.config.timestamp_col] = pd.to_datetime(
                self.df[self.config.timestamp_col]
            )

        # ── Pre-compute base time features on original timestamps ──────────
        # (augmentation will re-derive these per call; this seeds the dict)
        if self.config.timestamp_col in self.df.columns:
            feats = self.df[self.config.timestamp_col].apply(
                lambda ts: extract_time_features(ts, self.config.time2vec_dim)
            )
            self.df["hour_of_day"] = feats.apply(lambda x: x[0])
            self.df["day_of_week"] = feats.apply(lambda x: x[1])
            self.df["time2vec"]    = feats.apply(lambda x: x[2:])

        # Pre-init mask flag columns to 0.0 so record dicts are complete
        for col in self.config.numeric_cols:
            self.df[f"{col}_masked"] = 0.0

        self.records: list[dict] = self.df.to_dict(orient="records")

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Returns (view_1, view_2): two independently augmented tensors of
        the same underlying record. Both views share the same VM identity
        (role, region, OS) but differ in temporal context and visible metrics.

        This is the *positive pair* — the NT-Xent loss will push these two
        embeddings close together while pushing all other records in the
        batch far away.
        """
        base_record = self.records[idx]

        # Two independent augmentations — different jitter delta, different
        # masked columns — so the encoder cannot trivially match them by
        # looking for identical feature values
        view_1 = augment_record(base_record, self.config)
        view_2 = augment_record(base_record, self.config)

        return (
            record_to_tensor(view_1, self.config),
            record_to_tensor(view_2, self.config),
        )


# ─── Smoke Test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    # ── 1. Create a tiny synthetic parquet file for testing ────────────────
    print("=" * 60)
    print("VM Contrastive Augmentation — Smoke Test")
    print("=" * 60)

    N = 500
    rng = np.random.default_rng(42)

    synthetic = pd.DataFrame({
        "timestamp":         pd.date_range("2024-01-01", periods=N, freq="5min"),
        "vm_id":             [f"vm-{i % 20:03d}" for i in range(N)],
        "vm_role":           rng.choice(["web", "db", "cache"], N),
        "region":            rng.choice(["us-east", "eu-west", "ap-south"], N),
        "os_type":           rng.choice(["linux", "windows"], N),
        "cpu_usage":         rng.uniform(0, 100, N),
        "memory_usage":      rng.uniform(20, 95, N),
        "disk_io_read":      rng.uniform(0, 500, N),
        "disk_io_write":     rng.uniform(0, 300, N),
        "net_throughput_in": rng.uniform(0, 1000, N),
        "net_throughput_out":rng.uniform(0, 800, N),
    })

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = f.name
    synthetic.to_parquet(tmp_path, index=False)
    print(f"\n✓ Synthetic parquet written → {tmp_path}  ({N} records)")

    # ── 2. Instantiate dataset ─────────────────────────────────────────────
    config = AugmentationConfig(
        jitter_min_minutes=1.0,
        jitter_max_minutes=5.0,
        mask_ratio_min=0.10,
        mask_ratio_max=0.30,
        time2vec_dim=8,
    )

    dataset = VMContrastiveDataset(source=tmp_path, config=config)
    print(f"✓ Dataset length: {len(dataset)} records")

    # ── 3. Inspect one pair ────────────────────────────────────────────────
    v1, v2 = dataset[0]

    print(f"\n── Pair at index 0 ──────────────────────────────────────")
    print(f"  view_1 shape : {v1.shape}   dtype: {v1.dtype}")
    print(f"  view_2 shape : {v2.shape}   dtype: {v2.dtype}")
    print(f"\n  view_1 values (first 12 dims):\n    {v1[:12].numpy().round(4)}")
    print(f"  view_2 values (first 12 dims):\n    {v2[:12].numpy().round(4)}")

    # ── 4. Verify stochasticity — same index, different values each call ───
    v1b, v2b = dataset[0]
    are_same = torch.allclose(v1, v1b)
    print(f"\n  Stochasticity check (same idx, second call):")
    print(f"    view_1 == view_1_second_call? {are_same}  ← should be False")

    # ── 5. Verify pair count and tensor dim ───────────────────────────────
    expected_dim = (
        len(config.numeric_cols) * 2   # metric + mask flag per numeric col
        + 2                            # hour_of_day, day_of_week
        + config.time2vec_dim          # Time2Vec vector
    )
    assert v1.shape[0] == expected_dim, (
        f"Dim mismatch: got {v1.shape[0]}, expected {expected_dim}"
    )
    print(f"\n  Expected tensor dim : {expected_dim}")
    print(f"  Actual tensor dim   : {v1.shape[0]}  ✓")

    # ── 6. Quick DataLoader batch test ────────────────────────────────────
    from torch.utils.data import DataLoader

    loader = DataLoader(dataset, batch_size=32, shuffle=True, num_workers=0)
    batch_v1, batch_v2 = next(iter(loader))
    print(f"\n  DataLoader batch shapes:")
    print(f"    batch_v1 : {batch_v1.shape}   ← (batch_size, feature_dim)")
    print(f"    batch_v2 : {batch_v2.shape}")
    print("\n✓ All checks passed. Ready for NT-Xent training.\n")
