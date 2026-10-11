"""Validated configuration loading for local and production entry points."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


class ConfigLoader:
    """Load YAML configuration once and provide dotted-path access."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self._config = dict(config)

    @classmethod
    def from_file(cls, path: str | Path) -> "ConfigLoader":
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Configuration root must be a mapping: {config_path}")
        return cls(loaded)

    @property
    def data(self) -> dict[str, Any]:
        return dict(self._config)

    def get(self, key: str, default: Any = None) -> Any:
        value: Any = self._config
        for part in key.split("."):
            if not isinstance(value, Mapping) or part not in value:
                return default
            value = value[part]
        return value

    def require(self, key: str) -> Any:
        value = self.get(key)
        if value is None:
            raise KeyError(f"Missing required configuration key: {key}")
        return value


__all__ = ["ConfigLoader"]
