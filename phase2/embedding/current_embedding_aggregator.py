"""
phase2/embedding/current_embedding_aggregator.py
=====================================================
P2-M5  Current Embedding — CurrentEmbeddingAggregator
CAPSTONE-189

[P2-M5 CurrentEmbeddingAggregator]  (primer, Project Directory Structure §6b)
Groups (batch,128) InferenceEncoder output by entity_id. Mean-pools per
entity then re-applies L2 normalisation (normalise AFTER mean, not
before). Returns List[CurrentEmbedding]. Lightweight -- no neural network.

Why an entity can appear more than once in a batch
----------------------------------------------------
P2-M2's RecordEncoder windows an entity's records into seq_len-event
chunks (see reference_encoder_service.py's identical windowing logic for
P2-M4). Within one 5-15 min ingestion EventBatch, a very active entity
can span more than one window, so P2-M3's InferenceEncoder can emit
several (128,) embeddings for the same entity_id in a single batch. This
class collapses those back down to ONE "current behavior fingerprint"
per entity via mean-pool + re-normalise, which is what P2-M7 compares
against the entity's centroid.

SRP / "lightweight" note
--------------------------
No torch, no nn.Module, no gradient anything here (per the planner: "no
neural network"). Pure NumPy grouping + averaging. This class does not
know about EntityStore, CosineDeviationScorer, or the encoder — it only
turns encoder output into the CurrentEmbedding dataclass shape those
downstream modules expect (GRASP: Creator — "CurrentEmbeddingAggregator
creates CurrentEmbedding. It has all the data: entity_id, encoded
embeddings, batch_ts.").
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Sequence, Union

import numpy as np
import torch

from shared.types import CurrentEmbedding

logger_obj: logging.Logger = logging.getLogger(__name__)


class CurrentEmbeddingAggregator:
    """Stateless — holds no model, no config beyond what's passed per call."""

    def aggregate_embeddings(
        self,
        entity_ids: Sequence[str],
        embeddings: Union[np.ndarray, "torch.Tensor"],
        cloud_provider_by_entity_id: Dict[str, str],
        batch_ts: datetime,
    ) -> List[CurrentEmbedding]:
        """
        Parameters
        ----------
        entity_ids:
            Length-N sequence of entity_ids, positionally aligned with
            `embeddings` rows. entity_ids MAY repeat (see module
            docstring) — every row belonging to the same entity_id is
            pooled together regardless of position.
        embeddings:
            Shape (N, 128) — InferenceEncoder output, one row per
            entity_ids[i]. Accepts a torch.Tensor (moved to CPU/NumPy
            internally) or an ndarray directly, so callers don't need to
            know this class has no torch dependency of its own.
        cloud_provider_by_entity_id:
            entity_id -> cloud provider string (AWS/Azure/GCP/OCI),
            sourced by the caller from the batch's RawRecords. A missing
            entity_id falls back to "Unknown" (logged) rather than
            raising — a metadata gap should never block scoring.
        batch_ts:
            UTC timestamp of the ingestion batch these embeddings came
            from; stamped onto every output CurrentEmbedding.

        Returns
        -------
        List[CurrentEmbedding]
            One per unique entity_id in `entity_ids`, order not
            guaranteed to match input order (grouped internally).

        Raises
        ------
        ValueError
            If len(entity_ids) != embeddings.shape[0], or embeddings is
            not 2-D — these indicate a caller bug upstream, not a normal
            runtime condition to silently paper over.
        """
        if isinstance(embeddings, torch.Tensor):
            embeddings = embeddings.detach().cpu().numpy()
        embeddings = np.asarray(embeddings, dtype=np.float32)

        if embeddings.ndim != 2 or embeddings.shape[1] != 128:
            raise ValueError(
                f"[CurrentEmbeddingAggregator] embeddings must be shape (N, 128), "
                f"got {embeddings.shape}"
            )
        if len(entity_ids) != embeddings.shape[0]:
            raise ValueError(
                f"[CurrentEmbeddingAggregator] len(entity_ids)={len(entity_ids)} does not "
                f"match embeddings.shape[0]={embeddings.shape[0]}"
            )

        rows_by_entity_id: Dict[str, List[int]] = defaultdict(list)
        for row_idx, entity_id in enumerate(entity_ids):
            rows_by_entity_id[entity_id].append(row_idx)

        current_embeddings: List[CurrentEmbedding] = []
        for entity_id, row_indices in rows_by_entity_id.items():
            entity_embs = embeddings[row_indices]  # (record_count, 128)
            record_count = entity_embs.shape[0]

            # Mean-pool FIRST, normalise AFTER — a mean of unit vectors
            # does not itself lie on the unit sphere, so this order
            # matters (planner's explicit "What to Watch Out For").
            pooled_emb = entity_embs.mean(axis=0)
            norm = float(np.linalg.norm(pooled_emb))
            pooled_emb = (pooled_emb / norm if norm > 0 else pooled_emb).astype(np.float32)

            cloud_provider = cloud_provider_by_entity_id.get(entity_id)
            if cloud_provider is None:
                cloud_provider = "Unknown"
                logger_obj.warning(
                    "[CurrentEmbeddingAggregator] No cloud_provider for entity_id=%s "
                    "— defaulting to 'Unknown'",
                    entity_id,
                )

            if record_count == 1:
                logger_obj.debug(
                    "[CurrentEmbeddingAggregator] entity_id=%s had only 1 record in "
                    "this batch (mean-pool over 1 vector is a no-op).",
                    entity_id,
                )

            current_embeddings.append(
                CurrentEmbedding(
                    entity_id=entity_id,
                    emb=pooled_emb,
                    batch_ts=batch_ts,
                    n_records=record_count,
                    cloud_provider=cloud_provider,
                )
            )

        logger_obj.info(
            "[CurrentEmbeddingAggregator] Aggregated %d rows -> %d unique entities "
            "(batch_ts=%s)",
            embeddings.shape[0], len(current_embeddings), batch_ts,
        )
        return current_embeddings
