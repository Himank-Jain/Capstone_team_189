"""
phase2/encoding/categorical_encoder.py
==========================================
P2-M2  |  CategoricalEncoder â€” string -> vocab index for the 4 categorical
fields (cloud, entity_type, namespace, metric_name).

Must match streaming_aug_pairs_dataset.py's encoding EXACTLY:
    df[f"_enc_{col}"] = df[col].map(lambda v: vocab_map.get(str(v), 0))

i.e. cast to str() before lookup, default to 0 (PAD/UNK) on any miss â€”
including brand-new metric_names / cloud values never seen in training.
This class does NOT own nn.Embedding tables â€” those live inside
TstccEncoder.EmbeddingLayer (already trained). This class only produces
the integer indices that EmbeddingLayer's forward() expects.
"""

from __future__ import annotations

import logging
from typing import Dict

from shared.constants import AUG_PAIRS_CATEGORICAL_COLS as AUG_CATEGORICAL_COLS

logger_obj = logging.getLogger(__name__)


class CategoricalEncoder:
    """
    Parameters
    ----------
    vocab_maps_dict:
        {"cloud": {label: idx}, "entity_type": {...}, "namespace": {...},
        "metric_name": {...}} â€” sourced from FeatureMetaStore, which in
        turn must come from the SAME compute_vocab_sizes() output used to
        train the loaded TstccEncoder checkpoint.
    """

    def __init__(self, vocab_maps_dict: Dict[str, Dict[str, int]]) -> None:
        missing = [c for c in AUG_CATEGORICAL_COLS if c not in vocab_maps_dict]
        if missing:
            raise ValueError(
                f"[CategoricalEncoder] vocab_maps_dict is missing required "
                f"column(s): {missing}"
            )
        self._vocab_maps_dict = vocab_maps_dict
        self._oov_counts: Dict[str, int] = {c: 0 for c in AUG_CATEGORICAL_COLS}

    def encode(self, column: str, raw_value: str) -> int:
        """
        Map one raw string value to its vocab index for `column`.
        Returns 0 (PAD/UNK) on any value not seen during training â€”
        this is the expected, graceful path for new cloud resources, not
        an error condition.
        """
        vocab_map = self._vocab_maps_dict[column]
        idx = vocab_map.get(str(raw_value), 0)
        if idx == 0:
            self._oov_counts[column] += 1
            logger_obj.debug(
                "[CategoricalEncoder] OOV value for '%s': %r -> UNK(0)", column, raw_value
            )
        return idx

    @property
    def oov_counts(self) -> Dict[str, int]:
        """Running count of OOV lookups per column â€” useful as a health
        metric to catch vocab drift (e.g. a metric_name mismatch)."""
        return dict(self._oov_counts)
