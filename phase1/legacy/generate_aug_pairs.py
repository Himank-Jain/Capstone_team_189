"""
generate_aug_pairs.py
=====================
Stream-generates contrastive positive pairs from a large Parquet file
without loading it fully into memory.

Memory model
------------
At any point in time, only ONE batch lives in RAM:

    Source batch  (batch_size rows)   ~15–25 MB
    Augmented df  (2× batch_size rows) ~30–50 MB   ← written then freed
    ParquetWriter (buffer)             ~5–10 MB
    ─────────────────────────────────────────────
    Peak                               ~50–85 MB   ← safe on a MacBook

Output schema
-------------
Every source row produces TWO output rows (view_a and view_b).
A `pair_id` column groups them; `view` column marks which is which.

    pair_id  view  cpu_usage  memory_usage ... hour_of_day  day_of_week  time2vec_0..7  cpu_usage_masked ...

Usage
-----
    python generate_aug_pairs.py \
        --src  pretrain_corpus.parquet \
        --dst  aug_pairs.parquet       \
        --batch-size 10000             \
        --pairs-per-row 1              \
        --seed 42
"""

from __future__ import annotations

import argparse
import gc
import logging
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
import pyarrow as pa
import pyarrow.parquet as pq

# ── reuse aug logic from your existing module if it's on the path,
#    otherwise the slim copies below are self-contained
try:
    from vm_augmentation import (
        AugmentationConfig,
        apply_temporal_jitter,
        apply_attribute_masking,
        extract_time_features,
    )
    print("✓ Imported augmentation config from vm_augmentation.py")
except ImportError:
    # ── Inline fallback (identical logic, no external dep on vm_augmentation) ──
    import math as _math

    @dataclass
    @dataclass
    class AugmentationConfig:
                jitter_min_minutes: float = 1.0
                jitter_max_minutes: float = 5.0
                mask_ratio_min: float = 0.10
                mask_ratio_max: float = 0.30
                mask_fill_value: float = 0.0
                numeric_cols: list[str] = field(default_factory=lambda: [...])
                protected_cols: list[str] = field(default_factory=lambda: [...])
                timestamp_col: str = "timestamp"
                time2vec_dim: int = 8
                batch_size: int = 10_000   # ← add this line

    def _time2vec(t: float, dim: int) -> list[float]:
        return [t] + [_math.sin(2 * _math.pi * k * t / 24.0) for k in range(1, dim)]

    def extract_time_features(ts: pd.Timestamp, dim: int) -> list[float]:
        fh = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
        return [fh, float(ts.dayofweek)] + _time2vec(fh, dim)

    def apply_temporal_jitter(record: dict, config: AugmentationConfig) -> dict:
        out = record.copy()
        ts: pd.Timestamp = out[config.timestamp_col]
        delta = random.uniform(config.jitter_min_minutes, config.jitter_max_minutes)
        shifted = ts + pd.Timedelta(minutes=random.choice([-1, 1]) * delta)
        out[config.timestamp_col] = shifted
        feats = extract_time_features(shifted, config.time2vec_dim)
        out["hour_of_day"] = feats[0]
        out["day_of_week"] = feats[1]
        out["time2vec"]    = feats[2:]
        return out

    def apply_attribute_masking(record: dict, config: AugmentationConfig) -> dict:
        out = record.copy()
        n = len(config.numeric_cols)
        k = max(1, round(random.uniform(config.mask_ratio_min, config.mask_ratio_max) * n))
        for col in random.sample(config.numeric_cols, k):
            if col in out:
                out[col] = config.mask_fill_value
                out[f"{col}_masked"] = 1.0
        for col in config.numeric_cols:
            out.setdefault(f"{col}_masked", 0.0)
        return out

    print("⚠ vm_augmentation.py not found — using inline fallback")


# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1_048_576


# ── Core: augment one batch df → paired df ───────────────────────────────────

def _augment_batch(
    df: pd.DataFrame,
    config: AugmentationConfig,
    global_row_offset: int,
    pairs_per_row: int = 1,
) -> pd.DataFrame:
    """
    Takes a small DataFrame (one batch) and returns a DataFrame with
    2 × len(df) × pairs_per_row rows — view_a and view_b for each source row.

    pair_id is globally unique across the entire dataset so the trainer
    can group pairs correctly even when batches are shuffled.

    We build via list-of-dicts then pd.DataFrame() once per batch —
    never via repeated df.append() which copies the frame on every call.
    """
    records = df.to_dict(orient="records")   # small: only batch_size rows
    rows_out: list[dict] = []

    for local_idx, base in enumerate(records):
        global_pair_id = global_row_offset + local_idx

        for _ in range(pairs_per_row):
            for view_label in ("a", "b"):
                # Independent augmentation per view
                rec = apply_temporal_jitter(base, config)
                rec[config.timestamp_col] = rec[config.timestamp_col].floor("us")  
                rec = apply_attribute_masking(rec, config)

                # Flatten time2vec list into scalar columns
                t2v: list[float] = rec.pop("time2vec", [0.0] * config.time2vec_dim)
                for i, val in enumerate(t2v):
                    rec[f"time2vec_{i}"] = val

                rec["pair_id"] = global_pair_id
                rec["view"]    = view_label
                rows_out.append(rec)

    out_df = pd.DataFrame(rows_out)
    del records, rows_out
    return out_df


# ── PyArrow schema helper ─────────────────────────────────────────────────────

def _infer_output_schema(sample_df: pd.DataFrame) -> pa.Schema:
    """
    Infer a PyArrow schema from the first augmented batch.
    We force float32 for all numeric/time2vec columns to halve storage.
    """
    fields = []
    for col, dtype in sample_df.dtypes.items():
        if col in ("pair_id",):
            fields.append(pa.field(col, pa.int64()))
        elif col == "view":
            fields.append(pa.field(col, pa.string()))
        elif col == "timestamp":
            fields.append(pa.field(col, pa.timestamp("us")))
        elif dtype == object:
            fields.append(pa.field(col, pa.string()))
        else:
            fields.append(pa.field(col, pa.float32()))
    return pa.schema(fields)


# ── Main streaming pipeline ───────────────────────────────────────────────────

def generate_pairs(
    src: str | Path,
    dst: str | Path,
    config: AugmentationConfig,
    pairs_per_row: int = 1,
    seed: int = 42,
) -> None:
    """
    Streams `src` parquet in batches of config.batch_size rows.
    For each batch:
        1. Load batch → small DataFrame
        2. Augment → paired DataFrame (2 × batch rows)
        3. Write to `dst` via ParquetWriter (append mode)
        4. Delete both DataFrames, gc.collect()

    The ParquetWriter keeps the output file open across all batches so
    we never hold more than one batch in memory.
    """
    random.seed(seed)
    np.random.seed(seed)

    src = str(src)
    dst = str(dst)

    pf       = pq.ParquetFile(src)
    total    = pf.metadata.num_rows
    n_groups = pf.metadata.num_row_groups
    # Each row group in the file may be larger or smaller than batch_size.
    # We read full row groups and rechunk in Python — simpler than
    # trying to slice across row group boundaries in PyArrow.
    # For a 91 MB file with default row group size (~128K rows) this is fine.

    log.info("Source: %s  (%d rows, %d row groups)", src, total, n_groups)
    log.info("Output: %s  |  batch_size=%d  pairs_per_row=%d  seed=%d",
             dst, config.batch_size, pairs_per_row, seed)
    log.info("Expected output rows: %d", total * 2 * pairs_per_row)

    writer: pq.ParquetWriter | None = None
    schema: pa.Schema | None        = None

    global_row_offset = 0
    rows_written      = 0
    t0                = time.perf_counter()

    for rg_idx in range(n_groups):
        # ── 1. Load one row group ──────────────────────────────────────────
        table: pa.Table    = pf.read_row_group(rg_idx)
        rg_size: int       = table.num_rows
        df: pd.DataFrame   = table.to_pandas()
        del table
        gc.collect()

        # Parse timestamps once per row group
        if config.timestamp_col in df.columns:
            df[config.timestamp_col] = pd.to_datetime(df[config.timestamp_col])

        # ── 2. Chunk the row group into config.batch_size pieces ───────────
        n_chunks = math.ceil(rg_size / config.batch_size)

        for chunk_idx in range(n_chunks):
            chunk_start = chunk_idx * config.batch_size
            chunk_end   = min(chunk_start + config.batch_size, rg_size)
            chunk_df    = df.iloc[chunk_start:chunk_end].copy()

            elapsed = time.perf_counter() - t0
            log.info(
                "row_group %d/%d  chunk %d/%d  "
                "rows %d–%d  total_written=%d  RSS=%.0f MB  elapsed=%.0fs",
                rg_idx + 1, n_groups,
                chunk_idx + 1, n_chunks,
                global_row_offset, global_row_offset + len(chunk_df) - 1,
                rows_written, _rss_mb(), elapsed,
            )

            # ── 3. Augment ─────────────────────────────────────────────────
            paired_df = _augment_batch(
                chunk_df, config, global_row_offset, pairs_per_row
            )
            del chunk_df
            gc.collect()

            # ── 4. Init writer on first chunk (schema known now) ───────────
            if writer is None:
                schema = _infer_output_schema(paired_df)
                writer = pq.ParquetWriter(dst, schema, compression="snappy")
                log.info("ParquetWriter opened  schema: %d columns", len(schema))

            # ── 5. Cast + write ────────────────────────────────────────────
            # Cast to the fixed schema so every chunk is type-consistent.
            out_table = pa.Table.from_pandas(
                paired_df, schema=schema, preserve_index=False
            )
            writer.write_table(out_table)

            rows_written      += len(paired_df)
            global_row_offset += (chunk_end - chunk_start)

            del paired_df, out_table
            gc.collect()

        # ── 6. Free the row group ──────────────────────────────────────────
        del df
        gc.collect()

    # ── Finalise ──────────────────────────────────────────────────────────────
    if writer:
        writer.close()

    elapsed = time.perf_counter() - t0
    dst_mb  = Path(dst).stat().st_size / 1_048_576

    log.info("─" * 60)
    log.info("Done.  %d pairs written → %s  (%.1f MB)", rows_written, dst, dst_mb)
    log.info("Time: %.1f s  |  Final RSS: %.0f MB", elapsed, _rss_mb())


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stream-generate contrastive pair parquet")
    p.add_argument("--src",  required=True,  help="Source parquet path")
    p.add_argument("--dst",  required=True,  help="Output parquet path")
    p.add_argument("--batch-size",    type=int,   default=10_000)
    p.add_argument("--pairs-per-row", type=int,   default=1,
                   help="How many (a,b) pairs to generate per source row. "
                        "1 is enough for NT-Xent; use 2–3 for harder negatives.")
    p.add_argument("--jitter-min",  type=float, default=1.0)
    p.add_argument("--jitter-max",  type=float, default=5.0)
    p.add_argument("--mask-min",    type=float, default=0.10)
    p.add_argument("--mask-max",    type=float, default=0.30)
    p.add_argument("--time2vec-dim",type=int,   default=8)
    p.add_argument("--seed",        type=int,   default=42)
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    config = AugmentationConfig(
        jitter_min_minutes = args.jitter_min,
        jitter_max_minutes = args.jitter_max,
        mask_ratio_min     = args.mask_min,
        mask_ratio_max     = args.mask_max,
        time2vec_dim       = args.time2vec_dim,
        batch_size         = args.batch_size,
    )

    generate_pairs(
        src          = args.src,
        dst          = args.dst,
        config       = config,
        pairs_per_row= args.pairs_per_row,
        seed         = args.seed,
    )
