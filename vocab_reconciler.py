"""
VocabReconciler
----------------
Checks real-account categorical values (op_id, namespace/entity_type, metric_name)
against the vocab maps produced at training time by compute_vocab_sizes()
(see Directory Structure Section 2b / P1-M3), and falls back to the existing
<UNK> token for anything unseen — mirroring what P2-M2's CategoricalEncoder
must already do for OOV handling.

This module does NOT modify the trained vocab. It only classifies values as
known/unknown and tracks the OOV rate so it can be surfaced on Model Health.
Never silently expand the live vocab into the model's — that requires a
deliberate, versioned recalibration (Section 16.5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

UNK_TOKEN = "<UNK>"


class VocabReconciler:
    def __init__(self, feature_meta_path: Path):
        """feature_meta_path -> the SAME feature_meta.json version-locked with
        the active ArtifactBundle (P1-M6). Never load a different copy."""
        with open(feature_meta_path, "r") as f:
            meta = json.load(f)
        nested_maps = meta.get("vocab_maps", {})
        self.vocab_maps: Dict[str, Dict[str, int]] = {
            field: dict(nested_maps.get(field, meta.get(f"{field}_vocab", {})))
            for field in ("cloud", "entity_type", "namespace", "metric_name")
        }

    def resolve(self, field: str, value: str) -> tuple[str, bool]:
        """Returns (resolved_value, is_oov). resolved_value is either `value`
        itself (if known) or UNK_TOKEN."""
        vocab = self.vocab_maps.get(field, {})
        if value in vocab:
            return value, False
        return UNK_TOKEN, True

    def resolve_categorical_fields(self, categorical_fields: dict) -> tuple[dict, bool]:
        """Resolves all 4 categorical fields at once. Returns (resolved_dict, any_oov)."""
        resolved = {}
        any_oov = False
        for field in ("cloud", "entity_type", "namespace", "metric_name"):
            raw_value = categorical_fields.get(field, UNK_TOKEN)
            resolved_value, is_oov = self.resolve(field, raw_value)
            resolved[field] = resolved_value
            any_oov = any_oov or is_oov
        return resolved, any_oov
