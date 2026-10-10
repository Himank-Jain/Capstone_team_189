"""
scripts/generate_feature_meta.py
====================================
Generates and persists feature_meta.json — the file P1-M6's ArtifactBundle
needs in feature_meta_dict["vocab_maps"] to rebuild the encoder correctly,
and that P1-M5 currently only ever computes in memory (never saves).

Why this has to be its own step
----------------------------------
Both compute_vocab_sizes() and compute_metric_value_stats() are
non-deterministic in a subtle way: their *content* is fully determined by
the parquet file, but if you re-run them later against a DIFFERENT (even
slightly different, e.g. appended-to) parquet file, you can get different
vocab sizes / mappings than what the checkpoint you're registering was
actually trained against. The planner's "What to Watch Out For" flags
exactly this: feature_meta MUST be version-locked with the model, never
re-derived separately at registration or inference time.

So: run this ONCE, right after (or as part of) the same P1-M5 script run
that builds the FAISS index and encodes the corpus — off the SAME
aug_pairs.parquet — and register the resulting feature_meta.json alongside
that specific checkpoint. Do not regenerate it later against a newer file
and assume it still matches an older checkpoint.

Usage
-----
    python scripts/generate_feature_meta.py \\
        --parquet /path/to/aug_pairs.parquet \\
        --out config/feature_meta.json

Output format (consumed by ArtifactBundle.load()):
    {
      "vocab_maps": {
        "cloud":        {"AWS": 1, "Azure": 2, ...},
        "entity_type":  {...},
        "namespace":    {...},
        "metric_name":  {...}
      },
      "metric_value_stats": {
        "<metric_name>": {"mean": ..., "std": ...},
        ...
      },
      "source_parquet": "<path used>",
      "generated_at": "<ISO-8601 UTC timestamp>"
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on path

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%H:%M:%S")
logger_obj = logging.getLogger(__name__)


def _compute_vocab_and_stats(parquet_path_str: str) -> tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, float]]]:
    """
    Prefer P1-M2's streaming, full-file-pass implementations
    (compute_vocab_sizes / compute_metric_value_stats) if they're on the
    path — they're correct for large files. Fall back to an in-memory
    pandas computation (same logic tstcc_encoder.py's smoke test uses) if
    P1-M2's module isn't available, which is fine for a single parquet file
    that fits in memory.
    """
    try:
        from phase1.data.streaming_aug_pairs_dataset import compute_vocab_sizes, compute_metric_value_stats

        logger_obj.info("Using phase1.data.streaming_aug_pairs_dataset (P1-M2) — full-file streaming pass.")
        vocab_maps: Dict[str, Dict[str, int]] = compute_vocab_sizes(parquet_path_str)
        metric_value_stats = compute_metric_value_stats(parquet_path_str)

        # Convert (mean, std) tuples into {"mean": ..., "std": ...}
        metric_value_stats = {
            metric: {
                "mean": values[0],
                "std": values[1] if values[1] > 1e-6 else 1.0
            }
            for metric, values in metric_value_stats.items()
        }

        return vocab_maps, metric_value_stats

    except ImportError:
        logger_obj.warning(
            "phase1.data.streaming_aug_pairs_dataset not found on PYTHONPATH — "
            "falling back to loading the full parquet into memory with pandas. "
            "Fine for one file; for a very large corpus use P1-M2's streaming version instead."
        )
        import pandas as pd
        import pyarrow.parquet as pq

        df = pq.ParquetFile(parquet_path_str).read().to_pandas()

        vocab_maps = {
            "cloud": {v: i + 1 for i, v in enumerate(sorted(df["cloud"].dropna().unique()))},
            "entity_type": {v: i + 1 for i, v in enumerate(sorted(df["entity_type"].dropna().unique()))},
            "namespace": {v: i + 1 for i, v in enumerate(sorted(df["namespace"].dropna().unique()))},
            "metric_name": {v: i + 1 for i, v in enumerate(sorted(df["metric_name"].dropna().unique()))},
        }

        stats_df = df.groupby("metric_name")["value"].agg(["mean", "std"]).fillna(0.0)
        metric_value_stats = {
            metric_name: {"mean": float(row["mean"]), "std": float(row["std"] if row["std"] > 1e-6 else 1.0)}
            for metric_name, row in stats_df.iterrows()
        }
        return vocab_maps, metric_value_stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate feature_meta.json for P1-M6 ArtifactBundle registration.")
    parser.add_argument("--parquet", required=True, help="Path to the aug_pairs.parquet used to train the checkpoint.")
    parser.add_argument("--out", default="config/feature_meta.json", help="Output path for feature_meta.json.")
    args = parser.parse_args()

    vocab_maps, metric_value_stats = _compute_vocab_and_stats(args.parquet)

    logger_obj.info(
        "Vocab sizes: cloud=%d entity_type=%d namespace=%d metric_name=%d",
        len(vocab_maps["cloud"]), len(vocab_maps["entity_type"]),
        len(vocab_maps["namespace"]), len(vocab_maps["metric_name"]),
    )

    feature_meta_dict: Dict[str, Any] = {
        "vocab_maps": vocab_maps,
        "metric_value_stats": metric_value_stats,
        "source_parquet": str(Path(args.parquet).resolve()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as file_obj:
        json.dump(feature_meta_dict, file_obj, indent=2)

    logger_obj.info("feature_meta.json written -> %s", out_path.resolve())
    print(
        f"\nWrote {out_path}. Register it with the checkpoint trained on THIS "
        f"parquet file ({args.parquet}) -- do not reuse it for a different training run."
    )


if __name__ == "__main__":
    main()