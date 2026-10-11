"""Resolve live categorical values against a versioned feature vocabulary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

UNK_TOKEN = "<UNK>"


class VocabReconciler:
    def __init__(self, feature_meta_path: Path) -> None:
        with Path(feature_meta_path).open("r", encoding="utf-8") as handle:
            meta = json.load(handle)
        nested = meta.get("vocab_maps", {})
        self.vocab_maps: Dict[str, Dict[str, int]] = {
            field: dict(nested.get(field, meta.get(f"{field}_vocab", {})))
            for field in ("cloud", "entity_type", "namespace", "metric_name")
        }

    def resolve(self, field: str, value: str) -> tuple[str, bool]:
        if value in self.vocab_maps.get(field, {}):
            return value, False
        return UNK_TOKEN, True

    def resolve_categorical_fields(self, categorical_fields: dict) -> tuple[dict, bool]:
        resolved = {}
        any_oov = False
        for field in self.vocab_maps:
            value, is_oov = self.resolve(field, categorical_fields.get(field, UNK_TOKEN))
            resolved[field] = value
            any_oov = any_oov or is_oov
        return resolved, any_oov
