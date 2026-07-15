"""
scripts/build_faiss_index.py
================================
P1-M5 CLI entry point — builds and serializes the behavioral embedding space.

Usage
-----
    python scripts/build_faiss_index.py \\
        --parquet /path/to/aug_pairs.parquet \\
        --checkpoint model_registry/tstcc_encoder_final.pt \\
        --seq-len 32 \\
        --out model_registry/behavioral_space

What this script needs, and why
---------------------------------
1. --parquet   : the SAME aug_pairs.parquet (or equivalent full historical
                  corpus) used to train the encoder. It is read TWICE:
                    a) to recompute the categorical vocab (cloud, entity_type,
                       namespace, metric_name) so the encoder is rebuilt with
                       the exact same embedding-table shapes it was trained
                       with — vocab sizes are data-dependent and NOT hardcoded
                       (see phase1/models/tstcc_encoder.py module docstring).
                    b) to build the actual sequence windows that get encoded
                       into the behavioral space.
                  If P1-M2's phase1/data/streaming_aug_pairs_dataset.py
                  (compute_vocab_sizes / compute_metric_value_stats) is on
                  your PYTHONPATH, this script uses it. Otherwise it falls
                  back to computing vocab/stats directly from the loaded
                  DataFrame (fine for a single-file / smoke-test run, but for
                  a very large corpus prefer the streaming versions).

2. --checkpoint : a .pt file written by TstccEncoder.save_weights() /
                   save_checkpoint() during P1-M4 training
                   (e.g. model_registry/tstcc_encoder_final.pt).

Output
------
    {out}.faiss       — the trained + populated FAISS IndexIVFFlat
    {out}.meta.pkl     — parallel metadata (entity_id, timestamp, cloud, ...)

Register both paths in P1-M6's ArtifactBundle.faiss_index_path.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch

from phase1.embedding_space.batch_encoder import BatchEncoder, BatchEncoderConfigData
from phase1.embedding_space.faiss_indexer import FaissIndexer, build_faiss_index
from phase1.models.tstcc_encoder import build_tstcc_encoder_for_aug_pairs

try:
    from shared.constants import FAISS_N_LIST
except ImportError:
    FAISS_N_LIST = 100

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%H:%M:%S")
logger_obj = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the P1-M5 behavioral embedding space (FAISS).")
    parser.add_argument("--parquet", required=True, help="Path to aug_pairs.parquet (or historical corpus).")
    parser.add_argument("--checkpoint", required=True, help="Path to a trained TstccEncoder .pt checkpoint.")
    parser.add_argument("--seq-len", type=int, default=32, help="Reading events per sequence window (default 32).")
    parser.add_argument("--out", default="model_registry/behavioral_space",
                         help="Output path prefix (writes {out}.faiss + {out}.meta.pkl).")
    parser.add_argument("--nlist", type=int, default=FAISS_N_LIST, help="Requested IVF cluster count.")
    parser.add_argument("--batch-size", type=int, default=512, help="BatchEncoder batch size.")
    parser.add_argument("--device", default=None, help="cuda / cpu (default: auto-detect).")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # ── Step 1: vocab + per-metric value stats (must match training) ────────
    try:
        from phase1.data.streaming_aug_pairs_dataset import compute_vocab_sizes, compute_metric_value_stats
        logger_obj.info("Using phase1.data.streaming_aug_pairs_dataset for vocab/stats (P1-M2).")
        vocab_maps = compute_vocab_sizes(args.parquet)
        metric_value_stats = compute_metric_value_stats(args.parquet)
        print(metric_value_stats)
        cloud_map = vocab_maps["cloud"]
        etype_map = vocab_maps["entity_type"]
        ns_map = vocab_maps["namespace"]
        metric_map = vocab_maps["metric_name"]
        
        mean_map = {k: v[0] for k, v in metric_value_stats.items()}
        std_map = {k: (v[1] if v[1] > 1e-6 else 1.0) for k, v in metric_value_stats.items()}
    except ImportError:
        logger_obj.warning(
            "phase1.data.streaming_aug_pairs_dataset not found on PYTHONPATH — "
            "falling back to computing vocab/stats directly from the loaded parquet. "
            "This is fine for a single-file run but does NOT stream (loads the "
            "whole file); for a very large corpus, add P1-M2's module to your path instead."
        )
        df_full = pq.ParquetFile(args.parquet).read().to_pandas()
        cloud_map = {v: i + 1 for i, v in enumerate(sorted(df_full["cloud"].dropna().unique()))}
        etype_map = {v: i + 1 for i, v in enumerate(sorted(df_full["entity_type"].dropna().unique()))}
        ns_map = {v: i + 1 for i, v in enumerate(sorted(df_full["namespace"].dropna().unique()))}
        metric_map = {v: i + 1 for i, v in enumerate(sorted(df_full["metric_name"].dropna().unique()))}
        stats = df_full.groupby("metric_name")["value"].agg(["mean", "std"]).fillna(0.0)
        mean_map = stats["mean"].to_dict()
        std_map = {k: (v if v > 1e-6 else 1.0) for k, v in stats["std"].to_dict().items()}
        del df_full

    logger_obj.info(
        "Vocab sizes: cloud=%d entity_type=%d namespace=%d metric_name=%d",
        len(cloud_map), len(etype_map), len(ns_map), len(metric_map),
    )

    # ── Step 2: BatchEncoder — load checkpoint, disable projection ──────────
    batch_encoder = BatchEncoder(
        config=BatchEncoderConfigData(
            encoder_checkpoint_path_str=args.checkpoint,
            cloud_vocab_size_int=len(cloud_map),
            entity_type_vocab_size_int=len(etype_map),
            namespace_vocab_size_int=len(ns_map),
            metric_name_vocab_size_int=len(metric_map),
            batch_size_int=args.batch_size,
            device_str=args.device,
        )
    )

    # ── Step 3: build per-entity sequence windows from the corpus ───────────
    logger_obj.info("Loading corpus for sequence-window construction …")
    df = pq.ParquetFile(args.parquet).read().to_pandas()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["value"] = df["value"].fillna(0.0).astype(np.float32)
    df["value_norm"] = (
        (df["value"] - df["metric_name"].map(mean_map)) / df["metric_name"].map(std_map)
    ).astype(np.float32)
    df["hour_of_day_norm"] = df["hour_of_day"].fillna(0).astype(np.float32) / 24.0
    df["day_of_week_norm"] = df["day_of_week"].fillna(0).astype(np.float32) / 7.0

    view_col = "view" if "view" in df.columns else None

    numeric_list, categorical_list, ts_list, meta_list = [], [], [], []

    for entity_id, entity_df in df.sort_values(["entity_id", "timestamp"]).groupby("entity_id"):
        rows = entity_df if view_col is None else entity_df[entity_df[view_col] == "a"]
        if len(rows) < args.seq_len:
            continue
        for start in range(0, len(rows) - args.seq_len + 1, args.seq_len):  # non-overlapping windows
            window = rows.iloc[start:start + args.seq_len]
            numeric_list.append(window[["value_norm", "hour_of_day_norm", "day_of_week_norm"]].to_numpy(np.float32))
            categorical_list.append(np.stack([
                window["cloud"].map(cloud_map).fillna(0).to_numpy(),
                window["entity_type"].map(etype_map).fillna(0).to_numpy(),
                window["namespace"].map(ns_map).fillna(0).to_numpy(),
                window["metric_name"].map(metric_map).fillna(0).to_numpy(),
            ], axis=-1).astype(np.int64))
            frac_hour = (window["timestamp"].dt.hour + window["timestamp"].dt.minute / 60.0).to_numpy(np.float32) / 24.0
            ts_list.append(frac_hour[:, None])
            meta_list.append({
                "entity_id": str(entity_id),
                "timestamp": window["timestamp"].iloc[-1].isoformat(),
                "cloud_provider": window["cloud"].iloc[-1],
                "severity_label": None,
            })

    if not numeric_list:
        logger_obj.error("No entity had >= --seq-len=%d rows; nothing to index.", args.seq_len)
        sys.exit(1)

    numeric_tensor = torch.tensor(np.stack(numeric_list))
    categorical_tensor = torch.tensor(np.stack(categorical_list))
    timestamps_tensor = torch.tensor(np.stack(ts_list))

    logger_obj.info("Built %d sequence windows for encoding.", numeric_tensor.shape[0])

    # ── Step 4: encode the full corpus ───────────────────────────────────────
    embedding_corpus_array = batch_encoder.encode_records(numeric_tensor, categorical_tensor, timestamps_tensor)

    # ── Step 5: build + train the FAISS index, add vectors + metadata ──────
    ivf_index = build_faiss_index(embedding_corpus_array, nlist_int=args.nlist)
    indexer = FaissIndexer(index=ivf_index)
    indexer.add(embedding_corpus_array, meta_list)

    # ── Step 6: persist ────────────────────────────────────────────────────
    indexer.save(args.out)
    logger_obj.info("Behavioral embedding space written to %s.faiss / %s.meta.pkl", args.out, args.out)


if __name__ == "__main__":
    main()