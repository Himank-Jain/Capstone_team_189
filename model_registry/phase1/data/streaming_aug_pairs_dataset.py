"""
phase1/data/streaming_aug_pairs_dataset.py
=============================================
Memory-safe streaming dataset over the FULL aug_pairs.parquet file
(17.9M rows) for P1-M3/P1-M4 contrastive training.

Why streaming, not the map-style AugPairsDataset
---------------------------------------------------
``AugPairsDataset`` (aug_pairs_dataset.py) loads requested row groups fully
into a pandas DataFrame up front — fine for smoke tests on a few row groups,
but loading all 17.9M rows × 31 columns at once will exhaust RAM on most
training machines. This module instead reads ONE row group at a time
(mirrors the streaming pattern your teammate used in generate_corpus.py /
the aug_pairs.parquet writer: ~1M rows per row group, processed and freed
before moving to the next), and yields training pairs lazily as a
``torch.utils.data.IterableDataset``.

Trade-off: sequence windows are built only from rows within the same row
group. If an entity's rows straddle a row-group boundary, the tail end of
that entity's data in the next row group starts a fresh window set rather
than continuing seamlessly. Given ~1M rows per row group and most entities
having far fewer rows than that, this loses at most a handful of windows
per entity at row-group boundaries — an acceptable trade-off for being able
to train on the full file without ever holding more than ~1 row group in
memory.

Multi-worker support
---------------------
When used with ``DataLoader(num_workers > 0)``, row groups are sharded
round-robin across workers via ``torch.utils.data.get_worker_info()`` so
the file is read once total, not once per worker.

Schema — EVENT-BASED, not fixed-wide (revised)
-------------------------------------------------
Earlier versions of this module assumed every entity emits the same six
VM-style metrics (cpu_usage, memory_usage, ...) and pivoted long-format
rows into a wide row per timestep. That assumption does not hold: different
resource types emit entirely different, cloud-native metric sets (an Azure
Storage account emits Availability/Egress/Transactions/...; a VM emits
cpu_usage/memory_usage/...). There is no shared six-metric schema across
resource types.

This version drops the pivot entirely. Each row of aug_pairs.parquet is
treated as one (timestamp, metric_name, value) READING EVENT, and:
  * ``metric_name`` is now a 4th categorical embedding column, alongside
    cloud / entity_type / namespace — the model learns what each metric
    means rather than the pipeline hardcoding six column names.
  * ``value`` is the single numeric reading, z-score normalised PER
    metric_name (see :func:`compute_metric_value_stats`) since different
    metrics live on wildly different raw scales (e.g. 'Availability' in
    [0, 100] vs 'Available Memory Bytes' in the billions).
  * The legacy ``*_masked`` columns are no longer used as features. They
    were VM-shaped (six fixed flags) and don't correspond to whatever
    metric a given long-format row actually holds, so they carried no
    reliable per-event signal. Missingness is now implicit: a metric that
    wasn't emitted simply has no row, rather than a fake zero + mask flag.

Practical consequence for callers: a sequence window of length
``seq_len_int`` now spans ``seq_len_int`` consecutive READING EVENTS for
an entity (interleaved across whatever metrics it emits), not
``seq_len_int`` distinct timestamps. If an entity emits ~7 metrics per
timestamp, a 32-event window covers roughly 4-5 timestamps' worth of
history, not 32. Increase ``--seq-len`` accordingly if you want windows
that span more wall-clock time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch
from torch.utils.data import IterableDataset, get_worker_info

logger_obj = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Schema constants — MUST stay in sync with the aug_pairs.parquet writer
# and phase1/models/tstcc_encoder.py's AUG_PAIRS_* constants.
# ─────────────────────────────────────────────────────────────────────────────

# Long-format identity / grouping columns.
AUG_TIMESTAMP_COL: str = "timestamp"
AUG_ENTITY_COL: str = "entity_id"
AUG_VIEW_COL: str = "view"
AUG_PAIR_ID_COL: str = "pair_id"

# Each row is one metric reading: 'metric_name' identifies WHICH metric,
# 'value' is its raw reading. There is no fixed metric set across resource
# types — metric_name is treated as a categorical embedding (see below).
AUG_METRIC_NAME_COL: str = "metric_name"
AUG_VALUE_COL: str = "value"

# Time-scalar columns, normalised in-place to [0, 1) during preprocessing
# (hour_of_day / 24, day_of_week / 7) so they sit on a comparable scale to
# the z-scored value_norm column inside the shared numeric projection.
AUG_TIME_SCALAR_COLS: List[str] = ["hour_of_day", "day_of_week"]

# Categorical columns fed to EmbeddingLayer's nn.Embedding path, in order.
# metric_name is now included — THE ORDER OF THIS LIST IS THE CONTRACT.
AUG_CATEGORICAL_COLS: List[str] = ["cloud", "entity_type", "namespace", "metric_name"]

# Final ordered numeric feature list fed to EmbeddingLayer's nn.Linear path.
# 'value_norm' is a DERIVED column (z-scored per metric_name during
# preprocessing) — it does not exist as a raw column in the parquet file.
AUG_NUMERIC_COLS: List[str] = ["value_norm"] + AUG_TIME_SCALAR_COLS  # = 3

# Floor for per-metric std so a constant-valued metric never divides by ~0.
AUG_VALUE_NORM_EPS: float = 1e-6

# Columns actually needed from the parquet (column projection). We request
# 'metric_name' / 'value' directly — there are no wide metric columns to
# project instead, and the legacy *_masked columns are no longer read since
# they're not used as features.
AUG_REQUIRED_COLS: List[str] = sorted(set(
    AUG_TIME_SCALAR_COLS + AUG_CATEGORICAL_COLS
    + [AUG_TIMESTAMP_COL, AUG_ENTITY_COL, AUG_VIEW_COL, AUG_PAIR_ID_COL,
       AUG_METRIC_NAME_COL, AUG_VALUE_COL]
))


# ─────────────────────────────────────────────────────────────────────────────
# Vocabulary computation — single pass, columns-only (cheap on a 31-col file)
# ─────────────────────────────────────────────────────────────────────────────

def compute_vocab_sizes(parquet_path_str: str) -> Dict[str, Dict[str, int]]:
    """
    Scan the FULL file (column-projected — only the categorical columns,
    not all 31) once to build exact label→index vocabularies.

    This is far cheaper than it sounds: pyarrow reads only the requested
    columns per row group, so a 17.9M-row file with a handful of
    low-cardinality string columns is a few hundred MB at most, not the
    full file size.

    Returns
    -------
    dict
        {"cloud": {label: idx, ...}, "entity_type": {...}, "namespace": {...},
        "metric_name": {...}}. Index 0 is reserved for PAD/UNK in every column.
    """
    logger_obj.info("[compute_vocab_sizes] Scanning %s for categorical vocab …", parquet_path_str)
    pf = pq.ParquetFile(parquet_path_str)

    unique_sets: Dict[str, set] = {c: set() for c in AUG_CATEGORICAL_COLS}

    for rg_idx in range(pf.num_row_groups):
        table = pf.read_row_group(rg_idx, columns=AUG_CATEGORICAL_COLS)
        df_cols = table.to_pandas()
        for col in AUG_CATEGORICAL_COLS:
            unique_sets[col].update(df_cols[col].dropna().unique().tolist())

    vocab_maps: Dict[str, Dict[str, int]] = {}
    for col, values_set in unique_sets.items():
        sorted_values = sorted(str(v) for v in values_set)
        vocab_maps[col] = {v: i + 1 for i, v in enumerate(sorted_values)}  # 0 = PAD/UNK
        logger_obj.info("[compute_vocab_sizes] '%s': %d classes", col, len(sorted_values) + 1)

    return vocab_maps


def compute_metric_value_stats(parquet_path_str: str) -> Dict[str, Tuple[float, float]]:
    """
    Single pass over the FULL file (column-projected — only 'metric_name'
    and 'value') to compute per-metric mean/std for z-score normalisation.

    Why per-metric, not global
    ---------------------------
    Different metrics live on wildly different raw scales — e.g.
    'Availability' typically sits in [0, 100] while 'Available Memory Bytes'
    sits in the billions. A single global mean/std would let whichever
    metric has the largest raw magnitude dominate the shared numeric
    projection. Normalising per metric_name puts every metric on a
    comparable z-scored footing before it reaches the encoder.

    Returns
    -------
    dict
        {metric_name: (mean, std)}. std is floored at AUG_VALUE_NORM_EPS to
        avoid divide-by-zero on constant-valued metrics.
    """
    logger_obj.info(
        "[compute_metric_value_stats] Scanning %s for per-metric value stats …",
        parquet_path_str,
    )
    pf = pq.ParquetFile(parquet_path_str)

    sums: Dict[str, float] = {}
    sums_sq: Dict[str, float] = {}
    counts: Dict[str, int] = {}

    cols = [AUG_METRIC_NAME_COL, AUG_VALUE_COL]
    for rg_idx in range(pf.num_row_groups):
        table = pf.read_row_group(rg_idx, columns=cols)
        df_cols = table.to_pandas()
        df_cols[AUG_VALUE_COL] = df_cols[AUG_VALUE_COL].fillna(0.0).astype(np.float64)

        grouped = df_cols.groupby(AUG_METRIC_NAME_COL)[AUG_VALUE_COL]
        rg_sum = grouped.sum()
        rg_sum_sq = grouped.apply(lambda v: float((v ** 2).sum()))
        rg_count = grouped.count()

        for name, val in rg_sum.items():
            sums[name] = sums.get(name, 0.0) + float(val)
        for name, val in rg_sum_sq.items():
            sums_sq[name] = sums_sq.get(name, 0.0) + float(val)
        for name, val in rg_count.items():
            counts[name] = counts.get(name, 0) + int(val)

    stats: Dict[str, Tuple[float, float]] = {}
    for name, n in counts.items():
        if n == 0:
            continue
        mean = sums[name] / n
        var = max(sums_sq[name] / n - mean ** 2, 0.0)
        std = max(var ** 0.5, AUG_VALUE_NORM_EPS)
        stats[name] = (float(mean), float(std))
        logger_obj.info(
            "[compute_metric_value_stats] '%s': mean=%.4f std=%.4f n=%d",
            name, mean, std, n,
        )

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Streaming dataset
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StreamingDatasetConfigData:
    """
    Configuration for :class:`StreamingAugPairsDataset`.

    Parameters
    ----------
    parquet_path_str:
        Path to the full aug_pairs.parquet file.
    vocab_maps_dict:
        Pre-computed label→index maps from :func:`compute_vocab_sizes`.
        Build this ONCE before training (one pass over the categorical
        columns, including metric_name), then reuse across all epochs —
        don't recompute per epoch.
    metric_value_stats_dict:
        Pre-computed {metric_name: (mean, std)} maps from
        :func:`compute_metric_value_stats`. Build this ONCE before training
        for the same reason as vocab_maps_dict.
    seq_len_int:
        Sequence window length, in READING EVENTS (not distinct timesteps —
        see module docstring).
    stride_int:
        Step between window starts (stride < seq_len → overlapping windows).
    shuffle_within_row_group_bool:
        Shuffle window order within each row group before yielding, so
        consecutive batches aren't all from the same entity.
    """
    parquet_path_str: str
    vocab_maps_dict: Dict[str, Dict[str, int]]
    metric_value_stats_dict: Dict[str, Tuple[float, float]]
    seq_len_int: int = 32
    stride_int: int = 16
    shuffle_within_row_group_bool: bool = True


class StreamingAugPairsDataset(IterableDataset):
    """
    IterableDataset that streams aug_pairs.parquet row-group by row-group,
    yielding matched (view_a, view_b) sequence-window pairs without ever
    loading the full file into memory.

    Each window is a sequence of individual metric-reading EVENTS (one row
    per event: a single metric_name + value at a single timestamp), not a
    sequence of fixed-width timesteps — see module docstring for why.

    Parameters
    ----------
    config : StreamingDatasetConfigData
        Dataset configuration (DIP: injected via constructor).

    Example
    -------
    >>> vocab_maps = compute_vocab_sizes("aug_pairs.parquet")
    >>> value_stats = compute_metric_value_stats("aug_pairs.parquet")
    >>> cfg = StreamingDatasetConfigData(
    ...     parquet_path_str="aug_pairs.parquet",
    ...     vocab_maps_dict=vocab_maps,
    ...     metric_value_stats_dict=value_stats,
    ...     seq_len_int=32,
    ... )
    >>> dataset = StreamingAugPairsDataset(cfg)
    >>> loader  = DataLoader(dataset, batch_size=64, collate_fn=contrastive_collate_fn)
    >>> for batch_a, batch_b in loader:
    ...     ...
    """

    def __init__(self, config: StreamingDatasetConfigData) -> None:
        self._config_data: StreamingDatasetConfigData = config

        # NOTE — Windows picklability:
        # DataLoader(num_workers > 0) uses the 'spawn'/'forkserver' start
        # method on Windows, which PICKLES this entire Dataset object to
        # hand to each worker subprocess. pyarrow.parquet.ParquetFile /
        # ParquetReader objects cannot be pickled (non-trivial __cinit__,
        # no default __reduce__) — storing one as self._pf here would break
        # multi-worker loading on Windows with a cryptic
        # "TypeError: no default __reduce__" deep inside multiprocessing.
        # (Linux's default 'fork' start method copies process memory
        # directly instead of pickling, so this wouldn't show up there —
        # but the fix needs to work cross-platform since teammates may run
        # this on Colab/Linux while others run it locally on Windows.)
        #
        # Fix: open a ParquetFile just long enough to read num_row_groups,
        # then discard the handle. Each process (main process for
        # num_workers=0, or each worker subprocess for num_workers>0) opens
        # its OWN handle lazily on first use, after the pickling/fork has
        # already happened.
        self.num_row_groups_int: int = pq.ParquetFile(config.parquet_path_str).num_row_groups
        self._pf: Optional[pq.ParquetFile] = None

    def _get_parquet_file(self) -> pq.ParquetFile:
        """Lazily open (once per process) this process's own ParquetFile handle."""
        if self._pf is None:
            self._pf = pq.ParquetFile(self._config_data.parquet_path_str)
        return self._pf

    def __iter__(self) -> Iterator[Tuple[Dict[str, torch.Tensor], Dict[str, torch.Tensor]]]:
        worker_info = get_worker_info()
        if worker_info is None:
            row_group_indices = range(self.num_row_groups_int)
        else:
            # Shard row groups round-robin across workers so the file is
            # read once total, not once per worker.
            row_group_indices = range(
                worker_info.id, self.num_row_groups_int, worker_info.num_workers
            )

        for rg_idx in row_group_indices:
            yield from self._process_row_group(rg_idx)

    # ── Private helpers ───────────────────────────────────────────────────────


    def _process_row_group(
        self, rg_idx: int
    ) -> Iterator[Tuple[Dict[str, torch.Tensor], Dict[str, torch.Tensor]]]:
        cfg = self._config_data

        # ------------------------------------------------------------------
        # Read one parquet row group (long format — one row per event)
        # ------------------------------------------------------------------
        table = self._get_parquet_file().read_row_group(rg_idx, columns=AUG_REQUIRED_COLS)
        df = table.to_pandas()

        if df.empty:
            return

        # ------------------------------------------------------------------
        # Preprocess this row group
        # ------------------------------------------------------------------
        df[AUG_TIMESTAMP_COL] = pd.to_datetime(df[AUG_TIMESTAMP_COL], utc=True)

        # z-score 'value' PER metric_name using the precomputed global stats
        # (NOT stats from this row group alone — those would drift batch to
        # batch and defeat the point of normalisation).
        mean_map = {k: v[0] for k, v in cfg.metric_value_stats_dict.items()}
        std_map = {k: v[1] for k, v in cfg.metric_value_stats_dict.items()}

        df[AUG_VALUE_COL] = df[AUG_VALUE_COL].fillna(0.0).astype(np.float32)
        row_mean = df[AUG_METRIC_NAME_COL].map(mean_map).fillna(0.0).astype(np.float32)
        row_std = df[AUG_METRIC_NAME_COL].map(std_map).fillna(1.0).astype(np.float32)
        df["value_norm"] = ((df[AUG_VALUE_COL] - row_mean) / (row_std + AUG_VALUE_NORM_EPS)).astype(np.float32)

        # Normalise time scalars to [0, 1) so they sit on a comparable scale
        # to value_norm inside the shared numeric projection.
        df["hour_of_day"] = (df["hour_of_day"].fillna(0).astype(np.float32)) / 24.0
        df["day_of_week"] = (df["day_of_week"].fillna(0).astype(np.float32)) / 7.0

        # Encode categorical features (cloud, entity_type, namespace, metric_name)
        for col in AUG_CATEGORICAL_COLS:
            vocab_map = cfg.vocab_maps_dict[col]
            df[f"_enc_{col}"] = (
                df[col]
                .map(lambda value: vocab_map.get(str(value), 0))
                .astype(np.int64)
            )

        enc_cat_cols = [f"_enc_{c}" for c in AUG_CATEGORICAL_COLS]

        # ------------------------------------------------------------------
        # Split into the two augmentation views
        # ------------------------------------------------------------------
        df_a = df[df[AUG_VIEW_COL] == "a"]
        df_b = df[df[AUG_VIEW_COL] == "b"]

        # ------------------------------------------------------------------
        # Index by entity. Sort by pair_id, then timestamp, then metric_name
        # (stable tiebreaker since multiple metrics share the same timestamp
        # in event-based format) to keep both views aligned.
        # ------------------------------------------------------------------
        sort_cols = [AUG_PAIR_ID_COL, AUG_TIMESTAMP_COL, AUG_METRIC_NAME_COL]

        entities_a = {
            entity_id: group.sort_values(sort_cols).reset_index(drop=True)
            for entity_id, group in df_a.groupby(AUG_ENTITY_COL, sort=False)
        }
        entities_b = {
            entity_id: group.sort_values(sort_cols).reset_index(drop=True)
            for entity_id, group in df_b.groupby(AUG_ENTITY_COL, sort=False)
        }

        common_entities = list(set(entities_a.keys()) & set(entities_b.keys()))

        # ------------------------------------------------------------------
        # Build sliding-window index (windows are over EVENTS, not timesteps)
        # ------------------------------------------------------------------
        windows: List[Tuple[str, int]] = []

        for entity_id in common_entities:
            n_rows = min(len(entities_a[entity_id]), len(entities_b[entity_id]))

            if n_rows < cfg.seq_len_int:
                continue

            start_indices = range(0, n_rows - cfg.seq_len_int + 1, cfg.stride_int)
            windows.extend((entity_id, start) for start in start_indices)

        # ------------------------------------------------------------------
        # Shuffle windows inside this row group
        # ------------------------------------------------------------------
        if cfg.shuffle_within_row_group_bool:
            rng = np.random.default_rng()
            rng.shuffle(windows)

        # ------------------------------------------------------------------
        # Yield paired sequence windows
        # ------------------------------------------------------------------
        for entity_id, start in windows:
            end = start + cfg.seq_len_int

            rows_a = entities_a[entity_id].iloc[start:end]
            rows_b = entities_b[entity_id].iloc[start:end]

            yield (
                self._rows_to_seq_dict(rows_a, enc_cat_cols),
                self._rows_to_seq_dict(rows_b, enc_cat_cols),
            )

        # ------------------------------------------------------------------
        # Free memory before processing the next row group
        # ------------------------------------------------------------------
        del df, df_a, df_b, entities_a, entities_b

    @staticmethod
    def _rows_to_seq_dict(rows: pd.DataFrame, enc_cat_cols: List[str]) -> Dict[str, torch.Tensor]:
        numeric_tensor = torch.from_numpy(
            rows[AUG_NUMERIC_COLS].to_numpy(dtype=np.float32)
        )
        categorical_tensor = torch.from_numpy(
            rows[enc_cat_cols].to_numpy(dtype=np.int64)
        )
        ts = rows[AUG_TIMESTAMP_COL]
        frac_hour = (
            ts.dt.hour + ts.dt.minute / 60.0 + ts.dt.second / 3600.0
        ).to_numpy(dtype=np.float32) / 24.0
        timestamps_tensor = torch.from_numpy(frac_hour[:, np.newaxis])

        return {
            "numeric": numeric_tensor,
            "categorical": categorical_tensor,
            "timestamps": timestamps_tensor,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Collate function
# ─────────────────────────────────────────────────────────────────────────────

def contrastive_collate_fn(
    batch: List[Tuple[Dict[str, torch.Tensor], Dict[str, torch.Tensor]]]
) -> Tuple[
    Tuple[torch.Tensor, torch.Tensor, torch.Tensor],
    Tuple[torch.Tensor, torch.Tensor, torch.Tensor],
]:
    """
    Collate (seq_a, seq_b) pairs into batched tensors.

    Returns
    -------
    (batch_a, batch_b) where each is (numeric, categorical, timestamps)
    with shapes (B, seq_len, 3), (B, seq_len, 4), (B, seq_len, 1).
    All windows are fixed-length (seq_len_int), so no padding is needed.
    """
    def stack_view(view_list):
        return (
            torch.stack([v["numeric"] for v in view_list]),
            torch.stack([v["categorical"] for v in view_list]),
            torch.stack([v["timestamps"] for v in view_list]),
        )

    seqs_a, seqs_b = zip(*batch)
    return stack_view(list(seqs_a)), stack_view(list(seqs_b))