"""
phase1/train/train_tstcc.py
=============================
Full training run for the TSTCC contrastive encoder (P1-M3) using NT-Xent
loss (P1-M4) over the COMPLETE aug_pairs.parquet file.

This is a real training job, not a wiring check: it streams the entire
file epoch after epoch (never loading it fully into RAM), computes
contrastive loss on every batch, backpropagates, and checkpoints the
encoder every ENC_CHECKPOINT_FREQ (5) epochs to model_registry/.

Usage
-----
  python -m phase1.train.train_tstcc --parquet /path/to/aug_pairs.parquet

See TRAINING_GUIDE.md for the full flag reference and expected output.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import torch
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from phase1.data.streaming_aug_pairs_dataset import (
    StreamingAugPairsDataset,
    StreamingDatasetConfigData,
    compute_metric_value_stats,
    compute_vocab_sizes,
    contrastive_collate_fn,
)
from phase1.losses.ntxent_loss import NTXentLossComputer, NTXentLossConfigData
from phase1.models.tstcc_encoder import (
    build_tstcc_encoder_for_aug_pairs,
    ENC_CHECKPOINT_FREQ,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger_obj = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train TstccEncoder with NT-Xent contrastive loss on aug_pairs.parquet"
    )
    parser.add_argument("--parquet", required=True, help="Path to aug_pairs.parquet")
    parser.add_argument("--epochs", type=int, default=20, help="Number of training epochs (default: 20)")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size (default: 64)")
    parser.add_argument("--seq-len", type=int, default=32, help="Sequence window length (default: 32)")
    parser.add_argument("--stride", type=int, default=16, help="Window stride (default: 16, 50%% overlap)")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate (default: 3e-4)")
    parser.add_argument("--temperature", type=float, default=0.1, help="NT-Xent temperature (default: 0.1)")
    parser.add_argument("--num-workers", type=int, default=2, help="DataLoader worker processes (default: 2)")
    parser.add_argument("--checkpoint-dir", default="model_registry", help="Checkpoint output dir")
    parser.add_argument("--resume", default=None, help="Path to a checkpoint .pt file to resume from")
    parser.add_argument("--device", default=None, help="cuda / cpu (default: auto-detect)")
    parser.add_argument("--log-every", type=int, default=50, help="Log every N batches (default: 50)")
    parser.add_argument("--max-batches-per-epoch", type=int, default=None,
                         help="Cap batches/epoch for a quick test run (default: no cap, full file)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    device_str = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    device = torch.device(device_str)
    logger_obj.info("Device: %s", device_str)

    # ── Step 1: Build vocab + per-metric value stats from the full file ────
    # (one pass over the categorical columns, including metric_name, and a
    # second pass over metric_name/value for z-score normalisation stats)
    logger_obj.info("Computing categorical vocab from full file (single pass) …")
    t0 = time.time()
    vocab_maps = compute_vocab_sizes(args.parquet)
    logger_obj.info("Vocab computed in %.1fs: %s",
                     time.time() - t0,
                     {k: len(v) + 1 for k, v in vocab_maps.items()})

    logger_obj.info("Computing per-metric value stats (mean/std) from full file …")
    t0 = time.time()
    metric_value_stats = compute_metric_value_stats(args.parquet)
    logger_obj.info("Per-metric stats computed in %.1fs for %d metrics",
                     time.time() - t0, len(metric_value_stats))

    # ── Step 2: Build the encoder, sized to this file's vocab ──────────────
    encoder = build_tstcc_encoder_for_aug_pairs(
        cloud_vocab_size_int=len(vocab_maps["cloud"]),
        entity_type_vocab_size_int=len(vocab_maps["entity_type"]),
        namespace_vocab_size_int=len(vocab_maps["namespace"]),
        metric_name_vocab_size_int=len(vocab_maps["metric_name"]),
        use_projection_bool=True,
        checkpoint_dir_str=args.checkpoint_dir,
    ).to(device)

    n_params = sum(p.numel() for p in encoder.parameters())
    logger_obj.info("Encoder built: %s total parameters", f"{n_params:,}")

    # ── Step 3: Loss, optimizer, scheduler ──────────────────────────────────
    loss_fn = NTXentLossComputer(NTXentLossConfigData(temperature_float=args.temperature))
    optimizer = AdamW(encoder.parameters(), lr=args.lr)
    scheduler = CosineAnnealingLR(optimizer, T_max=args.epochs)

    start_epoch_int = 1
    if args.resume:
        logger_obj.info("Resuming from checkpoint: %s", args.resume)
        checkpoint = torch.load(args.resume, map_location=device)
        encoder.load_state_dict(checkpoint["state_dict"])
        if "optimizer_state_dict" in checkpoint:
            optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        start_epoch_int = checkpoint.get("epoch_int", 0) + 1
        logger_obj.info("Resumed at epoch %d", start_epoch_int)

    # ── Step 4: Streaming dataset / dataloader ──────────────────────────────
    dataset_cfg = StreamingDatasetConfigData(
        parquet_path_str=args.parquet,
        vocab_maps_dict=vocab_maps,
        metric_value_stats_dict=metric_value_stats,
        seq_len_int=args.seq_len,
        stride_int=args.stride,
        shuffle_within_row_group_bool=True,
    )

    # ── Step 5: Training loop ────────────────────────────────────────────────
    encoder.train()
    logger_obj.info(
        "Starting training: %d epochs, batch_size=%d, seq_len=%d, lr=%g",
        args.epochs, args.batch_size, args.seq_len, args.lr,
    )

    for epoch_int in range(start_epoch_int, args.epochs + 1):
        dataset = StreamingAugPairsDataset(dataset_cfg)   # fresh iterator each epoch
        loader = DataLoader(
            dataset,
            batch_size=args.batch_size,
            collate_fn=contrastive_collate_fn,
            num_workers=args.num_workers,
            drop_last=True,   # NT-Xent needs a consistent batch size for the positive-index math
        )

        epoch_loss_sum = 0.0
        n_batches_int = 0
        epoch_start_t = time.time()

        for batch_idx, ((num_a, cat_a, ts_a), (num_b, cat_b, ts_b)) in enumerate(loader, start=1):
            num_a, cat_a, ts_a = num_a.to(device), cat_a.to(device), ts_a.to(device)
            num_b, cat_b, ts_b = num_b.to(device), cat_b.to(device), ts_b.to(device)

            optimizer.zero_grad(set_to_none=True)

            z_a = encoder(num_a, cat_a, ts_a)
            z_b = encoder(num_b, cat_b, ts_b)

            loss = loss_fn(z_a, z_b)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(encoder.parameters(), max_norm=1.0)
            optimizer.step()

            epoch_loss_sum += loss.item()
            n_batches_int += 1

            if batch_idx % args.log_every == 0:
                running_avg = epoch_loss_sum / n_batches_int
                logger_obj.info(
                    "  epoch %d  batch %d  loss=%.4f  running_avg=%.4f",
                    epoch_int, batch_idx, loss.item(), running_avg,
                )

            if args.max_batches_per_epoch and batch_idx >= args.max_batches_per_epoch:
                logger_obj.info("  reached --max-batches-per-epoch=%d, ending epoch early",
                                 args.max_batches_per_epoch)
                break

        scheduler.step()

        if n_batches_int == 0:
            logger_obj.error(
                "Epoch %d produced 0 batches — check --seq-len/--batch-size against "
                "your data (entities may not have enough consecutive rows per row group).",
                epoch_int,
            )
            sys.exit(1)

        epoch_avg_loss = epoch_loss_sum / n_batches_int
        epoch_elapsed_s = time.time() - epoch_start_t
        logger_obj.info(
            "Epoch %d/%d done — avg_loss=%.4f  batches=%d  time=%.1fs  lr=%.2e",
            epoch_int, args.epochs, epoch_avg_loss, n_batches_int,
            epoch_elapsed_s, scheduler.get_last_lr()[0],
        )

        if epoch_int % ENC_CHECKPOINT_FREQ == 0 or epoch_int == args.epochs:
            ckpt_path = encoder.save_checkpoint(
                epoch_int=epoch_int,
                optimizer_state_dict=optimizer.state_dict(),
                loss_float=epoch_avg_loss,
            )
            logger_obj.info("Checkpoint saved: %s", ckpt_path)

    # ── Final save ────────────────────────────────────────────────────────────
    final_path = str(Path(args.checkpoint_dir) / "tstcc_encoder_final.pt")
    encoder.save_weights(final_path)
    logger_obj.info("Training complete. Final weights saved to: %s", final_path)


if __name__ == "__main__":
    main()