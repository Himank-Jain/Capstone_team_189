"""
phase2/encoding/feature_meta.py
===================================
P2-M2  |  FeatureMetaStore — holds the categorical vocab maps and
per-metric_name (mean, std) value stats that RecordEncoder must use.

CRITICAL (Phase 1 Architecture Addendum, Section 7 / P2-M2 action item):
these maps/stats MUST be the SAME ones computed once during training via
compute_vocab_sizes() / compute_metric_value_stats() in
streaming_aug_pairs_dataset.py — never re-derived independently at
inference time. A mismatched metric_name vocab or stale (mean, std) pair
silently produces wrong-scale readings with no crash to signal it.

P1-M6 (Model Registry / ArtifactBundle) is not built yet, so this class
supports two ways to obtain that data:
  1. from_registry_json(path)  — once feature_meta.json exists (P1-M6),
     point this at it. Expected shape documented below.
  2. from_dicts(vocab_maps, metric_value_stats) — inject the dicts
     directly, e.g. the exact objects returned by compute_vocab_sizes()/
     compute_metric_value_stats() during the same training run. Use this
     today; swap to from_registry_json once P1-M6 exists, with no
     changes needed anywhere else in P2-M2.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

logger_obj = logging.getLogger(__name__)


@dataclass
class FeatureMetaStore:
    """
    Parameters
    ----------
    vocab_maps_dict:
        {"cloud": {label: idx, ...}, "entity_type": {...}, "namespace": {...},
        "metric_name": {...}}. Index 0 reserved for PAD/UNK in every column
        — MUST match compute_vocab_sizes()'s convention exactly.
    metric_value_stats_dict:
        {metric_name: (mean, std)} — MUST match compute_metric_value_stats().
    """
    vocab_maps_dict: Dict[str, Dict[str, int]]
    metric_value_stats_dict: Dict[str, Tuple[float, float]]

    @classmethod
    def from_dicts(
        cls,
        vocab_maps: Dict[str, Dict[str, int]],
        metric_value_stats: Dict[str, object],
    ) -> "FeatureMetaStore":
        """Inject the vocab maps and metric stats directly — e.g. the
        exact objects produced by compute_vocab_sizes() /
        compute_metric_value_stats() during training, OR the
        feature_meta_dict embedded in an ArtifactBundle (which stores
        each metric's stats as {"mean": ..., "std": ...} rather than a
        bare tuple). Both shapes are normalized to (mean, std) tuples
        here, matching from_registry_json()'s same tolerance — do not
        assume callers already normalized this themselves."""
        normalized_stats: Dict[str, Tuple[float, float]] = {}
        for name, stat in metric_value_stats.items():
            if isinstance(stat, dict):
                normalized_stats[name] = (float(stat["mean"]), float(stat["std"]))
            else:
                normalized_stats[name] = (float(stat[0]), float(stat[1]))
        return cls(vocab_maps_dict=vocab_maps, metric_value_stats_dict=normalized_stats)

    @classmethod
    def from_registry_json(cls, feature_meta_path: str) -> "FeatureMetaStore":
        """
        Load from a feature_meta.json produced by P1-M6 (ArtifactBundle).

        Expected JSON shape
        --------------------
        {
          "vocab_maps": {"cloud": {"AWS": 1, ...}, "entity_type": {...},
                          "namespace": {...}, "metric_name": {...}},
          "metric_value_stats": {"cpu_usage": {"mean": 12.4, "std": 5.1}, ...}
        }
        (Also accepts the legacy [mean, std] list form for backward
        compatibility, in case an older exporter produced it that way.)
        """
        path = Path(feature_meta_path)
        if not path.exists():
            raise FileNotFoundError(
                f"[FeatureMetaStore] {path} not found — P1-M6 registry may not "
                f"be built yet. Use FeatureMetaStore.from_dicts() with the vocab/"
                f"stats objects from the training run in the meantime."
            )
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)

        vocab_maps = payload["vocab_maps"]
        metric_value_stats: Dict[str, Tuple[float, float]] = {}
        for name, stat in payload["metric_value_stats"].items():
            if isinstance(stat, dict):
                metric_value_stats[name] = (float(stat["mean"]), float(stat["std"]))
            else:  # legacy [mean, std] list/tuple form
                metric_value_stats[name] = (float(stat[0]), float(stat[1]))

        logger_obj.info(
            "[FeatureMetaStore] Loaded %d categorical cols, %d metric stats from %s",
            len(vocab_maps), len(metric_value_stats), path,
        )
        return cls(vocab_maps_dict=vocab_maps, metric_value_stats_dict=metric_value_stats)

    def to_registry_json(self, feature_meta_path: str) -> None:
        """Persist in the same shape from_registry_json() expects — useful
        for handing this exact training run's maps to P1-M6 once it exists."""
        payload = {
            "vocab_maps": self.vocab_maps_dict,
            "metric_value_stats": {
                name: [mean, std] for name, (mean, std) in self.metric_value_stats_dict.items()
            },
        }
        Path(feature_meta_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
