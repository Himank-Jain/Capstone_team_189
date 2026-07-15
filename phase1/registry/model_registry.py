"""
phase1/registry/model_registry.py
======================================
P1-M6  Outcome / Model Registry - ModelRegistry
CAPSTONE-189

ModelRegistry: register(bundle), get_latest() -> ArtifactBundle, get_by_version(v).
Manifest stored as JSON.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from phase1.registry.artifact_bundle import ArtifactBundle

logger_obj: logging.Logger = logging.getLogger(__name__)

MANIFEST_FILENAME: str = "artifacts_manifest.json"


@dataclass
class ModelRegistryConfigData:
    registry_dir_str: str = "model_registry"


class ModelRegistry:
    def __init__(self, config: ModelRegistryConfigData) -> None:
        self._config = config
        self._manifest_path = Path(config.registry_dir_str) / MANIFEST_FILENAME

    def _read_manifest(self) -> Dict:
        if not self._manifest_path.exists():
            return {"versions": {}, "latest_version": None}
        with self._manifest_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _write_manifest(self, manifest: Dict) -> None:
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self._manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, default=str)

    def register(self, bundle: ArtifactBundle) -> None:
        manifest = self._read_manifest()
        manifest["versions"][bundle.version_str] = bundle.to_manifest_dict()
        manifest["latest_version"] = bundle.version_str
        self._write_manifest(manifest)
        logger_obj.info("[ModelRegistry] Registered version=%s", bundle.version_str)

    def get_latest(self) -> ArtifactBundle:
        manifest = self._read_manifest()
        latest_version = manifest.get("latest_version")
        if latest_version is None or latest_version not in manifest.get("versions", {}):
            raise ValueError(
                f"[ModelRegistry] No registered versions found in {self._manifest_path}"
            )
        return ArtifactBundle.from_manifest_dict(manifest["versions"][latest_version])

    def get_by_version(self, version_str: str) -> ArtifactBundle:
        manifest = self._read_manifest()
        if version_str not in manifest.get("versions", {}):
            raise KeyError(f"[ModelRegistry] No such version registered: {version_str!r}")
        return ArtifactBundle.from_manifest_dict(manifest["versions"][version_str])

    def list_versions(self) -> list[str]:
        manifest = self._read_manifest()
        return list(manifest.get("versions", {}).keys())
