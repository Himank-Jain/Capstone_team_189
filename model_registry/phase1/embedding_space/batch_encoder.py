"""
phase1/embedding_space/batch_encoder.py
===========================================
P1-M5  Behavioral Embedding Space — BatchEncoder
Unified Predictive Analytics & Intelligent Alerting Platform  |  CAPSTONE-189

[P1-M5 FaissIndexer]  (primer, Project Directory Structure §6b)
Encodes all historical records via BatchEncoder(TstccEncoder). Builds FAISS
IndexIVFFlat(nlist=100). Metadata tagged: entity_id, timestamp, cloud_provider,
severity_label. serialize/load via faiss.write_index/read_index.
Key classes: BatchEncoder, FaissIndexer, EmbeddingVisualiser.

This file owns ONLY the BatchEncoder half of that pair (SRP) — offline,
batched record -> embedding conversion. Index construction, storage, and
search live in faiss_indexer.py.

Depends on: phase1/models/tstcc_encoder.py (P1-M3, TstccEncoder).
Consumed by: scripts/build_faiss_index.py, phase1/embedding_space/faiss_indexer.py
(indirectly, via the embedding_corpus_array it produces).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import torch

from phase1.models.tstcc_encoder import TstccEncoder, build_tstcc_encoder_for_aug_pairs

try:
    from shared.constants import ENC_EMBED_DIM
except ImportError:  # shared/ not yet on the path in a standalone checkout
    ENC_EMBED_DIM = 128

logger_obj: logging.Logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Module-scoped constants
# ─────────────────────────────────────────────────────────────────────────────

BATCH_ENCODER_DEFAULT_BATCH_SIZE: int = 512   # P1-M5 spec: batches of 512


@dataclass
class BatchEncoderConfigData:
    """
    Configuration for :class:`BatchEncoder`.

    Parameters
    ----------
    encoder_checkpoint_path_str:
        Path to a checkpoint produced by ``TstccEncoder.save_weights`` /
        ``save_checkpoint`` (P1-M3 / P1-M4). Ignored if an already-constructed
        ``TstccEncoder`` instance is injected directly into ``BatchEncoder``
        (DIP — see constructor).
    cloud_vocab_size_int, entity_type_vocab_size_int, namespace_vocab_size_int,
    metric_name_vocab_size_int:
        Vocab sizes the encoder was originally built with (P1-M2
        ``compute_vocab_sizes()``, fed into P1-M3
        ``build_tstcc_encoder_for_aug_pairs``). Only needed when loading from
        a checkpoint path rather than an injected encoder — MUST match the
        vocab sizes used at training time or ``load_weights`` will fail on
        embedding-table shape mismatch.
    batch_size_int:
        Number of records encoded per forward pass. Defaults to 512
        (P1-M5 spec).
    device_str:
        ``"cuda"`` / ``"cpu"``. Defaults to auto-detect.
    strict_load_bool:
        Forwarded to ``TstccEncoder.load_weights``.
    """
    encoder_checkpoint_path_str: Optional[str] = None
    cloud_vocab_size_int: int = 0
    entity_type_vocab_size_int: int = 0
    namespace_vocab_size_int: int = 0
    metric_name_vocab_size_int: int = 0
    batch_size_int: int = BATCH_ENCODER_DEFAULT_BATCH_SIZE
    device_str: Optional[str] = None
    strict_load_bool: bool = True


class BatchEncoder:
    """
    Runs historical telemetry records through a trained :class:`TstccEncoder`
    in fixed-size batches, with the projection head disabled, and returns a
    dense ``(N, 128)`` numpy embedding matrix ready for FAISS indexing.

    SRP note: this class owns *only* batched offline encoding. It does not
    know about FAISS, storage, or metadata — that's :class:`FaissIndexer`'s
    job (faiss_indexer.py).

    DIP note: accepts an already-constructed ``TstccEncoder`` via the
    ``encoder`` constructor argument so callers (and unit tests) can inject a
    small/untrained encoder without touching disk. When ``encoder`` is
    omitted, the class builds one from ``config`` and loads the checkpoint at
    ``config.encoder_checkpoint_path_str``.

    Parameters
    ----------
    config : BatchEncoderConfigData
        Batch size, device, and (optionally) checkpoint/vocab info.
    encoder : TstccEncoder | None
        Pre-built encoder to wrap. If ``None``, one is constructed and loaded
        from ``config.encoder_checkpoint_path_str``.
    """

    def __init__(
        self,
        config: BatchEncoderConfigData,
        encoder: Optional[TstccEncoder] = None,
    ) -> None:
        self._config_data: BatchEncoderConfigData = config

        device_str: str = config.device_str or ("cuda" if torch.cuda.is_available() else "cpu")
        self.device: torch.device = torch.device(device_str)

        if encoder is not None:
            self.encoder: TstccEncoder = encoder
        else:
            if not config.encoder_checkpoint_path_str:
                raise ValueError(
                    "[BatchEncoder] Either inject a TstccEncoder instance or "
                    "provide config.encoder_checkpoint_path_str to load one."
                )
            self.encoder = build_tstcc_encoder_for_aug_pairs(
                cloud_vocab_size_int=config.cloud_vocab_size_int,
                entity_type_vocab_size_int=config.entity_type_vocab_size_int,
                namespace_vocab_size_int=config.namespace_vocab_size_int,
                metric_name_vocab_size_int=config.metric_name_vocab_size_int,
                use_projection_bool=True,   # checkpoint was saved with head; load it, then disable
            )
            self.encoder.load_weights(
                config.encoder_checkpoint_path_str,
                map_location=device_str,
                strict_bool=config.strict_load_bool,
            )

        # Loads the encoder, disables projection head (P1-M5 spec step 1).
        self.encoder.disable_projection()
        self.encoder.to(self.device)
        self.encoder.eval()

        logger_obj.info(
            "[BatchEncoder] Ready.  device=%s  batch_size=%d  projection=OFF",
            device_str, config.batch_size_int,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def encode_records(
        self,
        numeric_tensor: torch.Tensor,
        categorical_tensor: torch.Tensor,
        timestamps_tensor: torch.Tensor,
        lengths_tensor: Optional[torch.Tensor] = None,
    ) -> np.ndarray:
        """
        Encode an entire record corpus in fixed-size batches of
        ``config.batch_size_int`` (512 by default) and return a single dense
        numpy embedding matrix.

        Parameters
        ----------
        numeric_tensor : Tensor
            Shape ``(N, seq_len, num_numeric)`` — full corpus, CPU or GPU.
        categorical_tensor : Tensor
            Shape ``(N, seq_len, num_categorical_fields)``.
        timestamps_tensor : Tensor
            Shape ``(N, seq_len, 1)``.
        lengths_tensor : Tensor | None
            Shape ``(N,)``. Pass ``None`` only when every record shares the
            same sequence length (no padding).

        Returns
        -------
        np.ndarray
            Shape ``(N, 128)``, dtype ``float32``, L2-normalised — directly
            consumable by ``build_faiss_index`` / ``FaissIndexer.add``.
        """
        num_records_int: int = numeric_tensor.size(0)
        batch_size_int: int = self._config_data.batch_size_int

        embedding_chunks_list: List[np.ndarray] = []

        for start_idx_int in range(0, num_records_int, batch_size_int):
            end_idx_int: int = min(start_idx_int + batch_size_int, num_records_int)

            numeric_batch_tensor: torch.Tensor = numeric_tensor[start_idx_int:end_idx_int].to(self.device)
            categorical_batch_tensor: torch.Tensor = categorical_tensor[start_idx_int:end_idx_int].to(self.device)
            timestamps_batch_tensor: torch.Tensor = timestamps_tensor[start_idx_int:end_idx_int].to(self.device)
            lengths_batch_tensor: Optional[torch.Tensor] = (
                lengths_tensor[start_idx_int:end_idx_int].to(self.device)
                if lengths_tensor is not None else None
            )

            with torch.no_grad():
                embedding_batch_tensor: torch.Tensor = self.encoder.encode_without_projection(
                    numeric_batch_tensor,
                    categorical_batch_tensor,
                    timestamps_batch_tensor,
                    lengths_batch_tensor,
                )

            embedding_chunks_list.append(embedding_batch_tensor.cpu().numpy().astype(np.float32))

            logger_obj.debug(
                "[BatchEncoder] Encoded records %d:%d / %d",
                start_idx_int, end_idx_int, num_records_int,
            )

        embedding_corpus_array: np.ndarray = (
            np.concatenate(embedding_chunks_list, axis=0)
            if embedding_chunks_list
            else np.empty((0, ENC_EMBED_DIM), dtype=np.float32)
        )

        logger_obj.info(
            "[BatchEncoder] Corpus encoding complete. shape=%s", embedding_corpus_array.shape
        )

        return embedding_corpus_array