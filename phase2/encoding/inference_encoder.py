"""
phase2/encoding/inference_encoder.py
========================================
P2-M3  Retrieved Encoder (Inference) — InferenceEncoder
CAPSTONE-189

Loads the trained TSTCC encoder in inference mode for generating current-
record embeddings — the same architecture as P1-M3, frozen, projection
head stripped.

DIP note (matching phase1/embedding_space/batch_encoder.py's own
pattern): accepts an already-loaded TstccEncoder via the `encoder`
constructor argument (e.g. from ArtifactBundle.load_latest(), which
already returns the encoder with projection disabled and eval() set) so
callers and unit tests can inject a small/untrained encoder without
touching disk or a real registry.

Consumes: RecordEncoder's raw (numeric, categorical, timestamps, lengths)
tensor tuple (P2-M2) — NOT a single pre-embedded tensor, since
RecordEncoder deliberately does not own any embedding logic (see
record_encoder.py's own module docstring for why).

Outputs: (batch, 128) L2-normalised embeddings, feeding P2-M5 (Current
Embedding) and compared against P2-M4 (Reference Encoder) output.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

import torch

from phase1.models.tstcc_encoder import TstccEncoder

logger_obj: logging.Logger = logging.getLogger(__name__)

INFERENCE_ENCODER_DEFAULT_CHUNK_SIZE: int = 64
INFERENCE_ENCODER_WARMUP_BATCHES: int = 3
INFERENCE_ENCODER_WARMUP_SEQ_LEN: int = 32


@dataclass
class LatencyStats:
    """
    Rolling per-batch encode latency tracker. Kept as a plain dataclass +
    list rather than a heavier metrics library dependency — P50/P95/P99
    are computed on demand from the raw sample list, which is more than
    fast enough at the batch-level (not per-record) granularity this
    tracks.

    Parameters
    ----------
    max_samples:
        Caps the raw sample list so long-running services don't leak
        memory — oldest samples are dropped once exceeded (a simple
        ring-buffer-by-truncation, not a strict FIFO, since exact ordering
        doesn't matter for percentile computation).
    """
    max_samples: int = 10_000
    _samples_ms: List[float] = field(default_factory=list)

    def record(self, latency_ms: float) -> None:
        self._samples_ms.append(latency_ms)
        if len(self._samples_ms) > self.max_samples:
            self._samples_ms = self._samples_ms[-self.max_samples:]

    def _percentile(self, p: float) -> float:
        if not self._samples_ms:
            return 0.0
        ordered = sorted(self._samples_ms)
        idx = min(len(ordered) - 1, int(round(p / 100.0 * (len(ordered) - 1))))
        return ordered[idx]

    @property
    def p50(self) -> float:
        return self._percentile(50)

    @property
    def p95(self) -> float:
        return self._percentile(95)

    @property
    def p99(self) -> float:
        return self._percentile(99)

    @property
    def count(self) -> int:
        return len(self._samples_ms)


class InferenceEncoder:
    """
    Parameters
    ----------
    encoder:
        An already-loaded TstccEncoder (e.g. from
        ``ArtifactBundle.load_latest()``). MUST already have its
        projection head disabled — this class asserts that rather than
        disabling it again itself, since re-deciding that here would
        duplicate a decision ArtifactBundle.load() already made and could
        silently diverge from it.
    chunk_size:
        Records per internal forward-pass chunk, to bound peak memory on
        large batches. Defaults to 64 per the P2-M3 spec.
    device:
        Defaults to the device the injected encoder is already on.
    warm_up:
        If True (default), immediately runs
        INFERENCE_ENCODER_WARMUP_BATCHES dummy batches of zeros through
        the encoder to pre-compile/pre-load CUDA kernels before the first
        real request pays that cost.
    """

    def __init__(
        self,
        encoder: TstccEncoder,
        chunk_size: int = INFERENCE_ENCODER_DEFAULT_CHUNK_SIZE,
        device: Optional[str] = None,
        warm_up: bool = True,
    ) -> None:
        if encoder.use_projection_bool:
            raise ValueError(
                "[InferenceEncoder] The injected encoder still has its projection "
                "head ENABLED — embeddings would come from the wrong (256-d "
                "pre-projection... actually 128-d post-projection-head) space. "
                "Call encoder.disable_projection() before injecting it here, or "
                "load it via ArtifactBundle.load_latest(), which already does this."
            )

        self.encoder = encoder
        self._chunk_size = chunk_size
        self.device = torch.device(device) if device else next(encoder.parameters()).device
        self.encoder.to(self.device)
        self.encoder.eval()

        self.latency_stats = LatencyStats()

        logger_obj.info(
            "[InferenceEncoder] Ready.  device=%s  chunk_size=%d",
            self.device, chunk_size,
        )

        if warm_up:
            self._run_warmup()

    # ── Warm-up ──────────────────────────────────────────────────────────────

    def _run_warmup(self) -> None:
        """Run dummy zero-batches through the encoder once at startup so
        the first real request doesn't pay CUDA kernel-compile /
        cudnn-autotune cost. Latencies from warm-up are NOT recorded into
        latency_stats — they're not representative of real traffic."""
        num_numeric = self.encoder._config_data.embedding_cfg.num_numeric_int
        num_categorical = len(self.encoder._config_data.embedding_cfg.categorical_fields_list)

        dummy_numeric = torch.zeros(1, INFERENCE_ENCODER_WARMUP_SEQ_LEN, num_numeric, device=self.device)
        dummy_categorical = torch.zeros(
            1, INFERENCE_ENCODER_WARMUP_SEQ_LEN, num_categorical, dtype=torch.long, device=self.device
        )
        dummy_timestamps = torch.zeros(1, INFERENCE_ENCODER_WARMUP_SEQ_LEN, 1, device=self.device)

        with torch.no_grad():
            for _ in range(INFERENCE_ENCODER_WARMUP_BATCHES):
                self.encoder(dummy_numeric, dummy_categorical, dummy_timestamps)

        logger_obj.info(
            "[InferenceEncoder] Warm-up complete (%d dummy batches).",
            INFERENCE_ENCODER_WARMUP_BATCHES,
        )

    # ── Public API ───────────────────────────────────────────────────────────

    def encode(
        self,
        numeric_tensor: torch.Tensor,
        categorical_tensor: torch.Tensor,
        timestamps_tensor: torch.Tensor,
        lengths_tensor: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        Encode a batch of RecordEncoder-produced tensors, internally
        chunked to `chunk_size` to bound peak memory. Records per-chunk
        latency into `self.latency_stats`.

        Parameters
        ----------
        numeric_tensor : (N, seq_len, num_numeric)
        categorical_tensor : (N, seq_len, num_categorical)
        timestamps_tensor : (N, seq_len, 1)
        lengths_tensor : (N,) or None

        Returns
        -------
        Tensor
            (N, 128) float32, L2-normalised.
        """
        n = numeric_tensor.size(0)
        chunks: List[torch.Tensor] = []

        for start in range(0, n, self._chunk_size):
            end = min(start + self._chunk_size, n)

            num_chunk = numeric_tensor[start:end].to(self.device)
            cat_chunk = categorical_tensor[start:end].to(self.device)
            ts_chunk = timestamps_tensor[start:end].to(self.device)
            len_chunk = lengths_tensor[start:end].to(self.device) if lengths_tensor is not None else None

            t0 = time.perf_counter()
            with torch.no_grad():
                emb_chunk = self.encoder(num_chunk, cat_chunk, ts_chunk, len_chunk)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.latency_stats.record(elapsed_ms)

            chunks.append(emb_chunk)

        return torch.cat(chunks, dim=0) if chunks else torch.empty(0, self.encoder._config_data.embed_dim_int)

    def encode_single(
        self,
        numeric_tensor: torch.Tensor,
        categorical_tensor: torch.Tensor,
        timestamps_tensor: torch.Tensor,
    ) -> torch.Tensor:
        """
        Convenience path for a single unbatched record. Accepts
        UNBATCHED tensors (seq_len, num_numeric) etc. and returns a
        single (128,) embedding vector (batch dim squeezed).
        """
        result = self.encode(
            numeric_tensor.unsqueeze(0),
            categorical_tensor.unsqueeze(0),
            timestamps_tensor.unsqueeze(0),
        )
        return result.squeeze(0)
