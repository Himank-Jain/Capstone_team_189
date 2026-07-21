"""
phase1/registry/model_registry.py
======================================
P1-M6  Outcome / Model Registry — ModelRegistry
Unified Predictive Analytics & Intelligent Alerting Platform  |  CAPSTONE-189

[P1-M6 ModelRegistry]  (primer, Project Directory Structure §6b)
ArtifactBundle(dataclass): version, encoder_path, faiss_index_path, config,
feature_meta, training_ts, val_loss.
ModelRegistry: register(bundle), get_latest() -> ArtifactBundle, get_by_version(v).
Manifest stored as JSON. ArtifactBundle.load() returns live encoder + FAISS index.
CRITICAL: feature_meta.json must be version-locked with encoder checkpoint.

GRASP note — Pure Fabrication: no real-world "model registry" entity exists
in the domain; this is a fabricated helper class to manage artifact
versioning cleanly without coupling Phase 1 output to Phase 2 input
(Project Directory Structure §4).

What to watch out for (per the AI Prompt Brief)
--------------------------------------------------
  * If multiple team members run training simultaneously, the manifest file
    can have write conflicts. This module takes an advisory OS-level file
    lock (fcntl.flock on POSIX) around every read-modify-write of the
    manifest, so concurrent register() calls serialize instead of racing.
    This is a lighter-weight substitute for MLflow, matching the planner's
    "add file locking or use MLflow" guidance.
  * feature_meta (vocab mappings) MUST match exactly between training and
    inference. This module does not itself enforce that beyond storing
    whatever ArtifactBundle.feature_meta_dict was given at register() time --
    it is the caller's job to always pass the SAME feature_meta_dict that was
    used to build the encoder currently being registered.

CLI
---
    python phase1/registry/model_registry.py --register \\
        --version 0.1.0 \\
        --encoder model_registry/tstcc_encoder_final.pt \\
        --faiss-index model_registry/behavioral_space \\
        --config config/config.json \\
        --feature-meta config/feature_meta.json \\
        --val-loss 0.1832

    python phase1/registry/model_registry.py --list
    python phase1/registry/model_registry.py --get-latest
    python phase1/registry/model_registry.py --get-version 0.1.0
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from phase1.registry.artifact_bundle import ArtifactBundle, extract_time2vec_params, load_json_file

logger_obj: logging.Logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# File locking helper (POSIX advisory lock around manifest read-modify-write)
# ─────────────────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _locked_manifest_file(lock_path_str: str):
    """
    Advisory exclusive lock around the manifest file, using fcntl.flock on
    POSIX. Blocks (does not busy-poll) until the lock is free, so concurrent
    register() calls from multiple team members serialize instead of
    corrupting the JSON manifest (per the planner's "What to Watch Out For").

    On non-POSIX platforms (no fcntl), falls back to no locking with a
    warning -- callers should prefer MLflow there, per the planner's note.
    """
    try:
        import fcntl
    except ImportError:
        logger_obj.warning(
            "[ModelRegistry] fcntl unavailable on this platform — manifest "
            "writes are NOT locked. Avoid concurrent register() calls, or use MLflow."
        )
        yield
        return

    Path(lock_path_str).parent.mkdir(parents=True, exist_ok=True)
    lock_file_obj = open(lock_path_str, "w")
    try:
        fcntl.flock(lock_file_obj, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_file_obj, fcntl.LOCK_UN)
        lock_file_obj.close()


# ─────────────────────────────────────────────────────────────────────────────
# ModelRegistry
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ModelRegistryConfigData:
    """
    Configuration for :class:`ModelRegistry`.

    Parameters
    ----------
    registry_dir_str : str
        Local directory holding ``artifacts_manifest.json`` (and, typically,
        the checkpoints/index files it points to). Used whenever
        ``use_s3_bool`` is ``False`` (the default).
    manifest_filename_str : str
        Manifest file name within ``registry_dir_str`` / the S3 prefix.
    use_s3_bool : bool
        If ``True``, read/write the manifest from S3 instead of local disk
        (per the planner's "(4) Save/load the registry from S3 or local
        path based on config flag"). Requires ``boto3``.
    s3_bucket_str, s3_prefix_str : str | None
        Target bucket/prefix when ``use_s3_bool`` is ``True``.
    """
    registry_dir_str: str = "model_registry"
    manifest_filename_str: str = "artifacts_manifest.json"
    use_s3_bool: bool = False
    s3_bucket_str: Optional[str] = None
    s3_prefix_str: str = ""


class ModelRegistry:
    """
    Versioned artifact registry backed by a JSON manifest
    (``artifacts_manifest.json``), local-disk or S3.

    Public surface (per the AI Prompt Brief): ``register(bundle)``,
    ``list_versions()``, ``get_latest()``, ``get_by_version(v)``.

    Parameters
    ----------
    config : ModelRegistryConfigData
        Storage backend + manifest location.
    """

    def __init__(self, config: ModelRegistryConfigData) -> None:
        self._config_data: ModelRegistryConfigData = config

        if config.use_s3_bool:
            try:
                import boto3  # noqa: F401  (import-checked here, used lazily below)
            except ImportError as exc:
                raise ImportError(
                    "[ModelRegistry] use_s3_bool=True requires boto3 "
                    "(`pip install boto3`)."
                ) from exc

        Path(config.registry_dir_str).mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def register(self, bundle: ArtifactBundle) -> None:
        """
        Add a new (or overwrite an existing) version entry to the manifest.

        Locks the manifest for the duration of the read-modify-write so
        concurrent registrations from other team members serialize rather
        than racing (see module docstring).

        Parameters
        ----------
        bundle : ArtifactBundle
            The artifact set to register. ``bundle.version_str`` is the key;
            registering the same version again overwrites that entry.
        """
        manifest_path_str, lock_path_str = self._manifest_paths()

        with _locked_manifest_file(lock_path_str):
            manifest_dict: Dict[str, Any] = self._read_manifest_unlocked(manifest_path_str)
            manifest_dict["versions"][bundle.version_str] = bundle.to_manifest_dict()
            manifest_dict["latest_version"] = self._compute_latest_version(manifest_dict["versions"])
            self._write_manifest_unlocked(manifest_path_str, manifest_dict)

        logger_obj.info(
            "[ModelRegistry] Registered version=%s  encoder=%s  faiss=%s",
            bundle.version_str, bundle.encoder_path, bundle.faiss_index_path,
        )

    def list_versions(self) -> List[str]:
        """Return all registered version strings, sorted ascending (semver)."""
        manifest_path_str, _ = self._manifest_paths()
        manifest_dict = self._read_manifest_unlocked(manifest_path_str)
        return sorted(manifest_dict["versions"].keys(), key=_version_sort_key)

    def get_latest(self) -> ArtifactBundle:
        """
        Return the highest-versioned :class:`ArtifactBundle` in the manifest.

        Raises
        ------
        LookupError
            If the manifest has no registered versions yet.
        """
        manifest_path_str, _ = self._manifest_paths()
        manifest_dict = self._read_manifest_unlocked(manifest_path_str)

        versions_list = list(manifest_dict["versions"].keys())
        if not versions_list:
            raise LookupError("[ModelRegistry.get_latest] No versions registered yet.")

        latest_version_str = manifest_dict.get("latest_version") or self._compute_latest_version(
            manifest_dict["versions"]
        )
        return ArtifactBundle.from_manifest_dict(manifest_dict["versions"][latest_version_str])

    def get_by_version(self, version_str: str) -> ArtifactBundle:
        """
        Return the :class:`ArtifactBundle` registered under an exact version.

        Parameters
        ----------
        version_str : str
            e.g. ``"0.1.0"``.

        Raises
        ------
        KeyError
            If that version was never registered.
        """
        manifest_path_str, _ = self._manifest_paths()
        manifest_dict = self._read_manifest_unlocked(manifest_path_str)

        if version_str not in manifest_dict["versions"]:
            raise KeyError(
                f"[ModelRegistry.get_by_version] version '{version_str}' not found. "
                f"Registered versions: {sorted(manifest_dict['versions'].keys())}"
            )
        return ArtifactBundle.from_manifest_dict(manifest_dict["versions"][version_str])

    # ── Private helpers ───────────────────────────────────────────────────────

    def _manifest_paths(self) -> "tuple[str, str]":
        manifest_path_str = str(Path(self._config_data.registry_dir_str) / self._config_data.manifest_filename_str)
        lock_path_str = manifest_path_str + ".lock"
        return manifest_path_str, lock_path_str

    def _read_manifest_unlocked(self, manifest_path_str: str) -> Dict[str, Any]:
        """Read the manifest (local or S3). Returns an empty skeleton if absent."""
        if self._config_data.use_s3_bool:
            raw_bytes = self._s3_get_object_bytes(manifest_path_str)
            if raw_bytes is None:
                return {"versions": {}, "latest_version": None}
            return json.loads(raw_bytes.decode("utf-8"))

        manifest_file = Path(manifest_path_str)
        if not manifest_file.exists():
            return {"versions": {}, "latest_version": None}
        with open(manifest_file, "r") as file_obj:
            return json.load(file_obj)

    def _write_manifest_unlocked(self, manifest_path_str: str, manifest_dict: Dict[str, Any]) -> None:
        """Write the manifest (local or S3)."""
        serialized_str = json.dumps(manifest_dict, indent=2, default=str)

        if self._config_data.use_s3_bool:
            self._s3_put_object_bytes(manifest_path_str, serialized_str.encode("utf-8"))
            return

        manifest_file = Path(manifest_path_str)
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish write: write to a temp file then replace, so a crash
        # mid-write never leaves a half-written manifest behind.
        tmp_file = manifest_file.with_suffix(manifest_file.suffix + ".tmp")
        with open(tmp_file, "w") as file_obj:
            file_obj.write(serialized_str)
        tmp_file.replace(manifest_file)

    @staticmethod
    def _compute_latest_version(versions_dict: Dict[str, Any]) -> Optional[str]:
        if not versions_dict:
            return None
        return sorted(versions_dict.keys(), key=_version_sort_key)[-1]

    def _s3_get_object_bytes(self, manifest_path_str: str) -> Optional[bytes]:
        import boto3
        from botocore.exceptions import ClientError

        s3_client = boto3.client("s3")
        key_str = f"{self._config_data.s3_prefix_str.rstrip('/')}/{Path(manifest_path_str).name}".lstrip("/")
        try:
            response = s3_client.get_object(Bucket=self._config_data.s3_bucket_str, Key=key_str)
            return response["Body"].read()
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def _s3_put_object_bytes(self, manifest_path_str: str, data_bytes: bytes) -> None:
        import boto3

        s3_client = boto3.client("s3")
        key_str = f"{self._config_data.s3_prefix_str.rstrip('/')}/{Path(manifest_path_str).name}".lstrip("/")
        s3_client.put_object(Bucket=self._config_data.s3_bucket_str, Key=key_str, Body=data_bytes)


def _version_sort_key(version_str: str):
    """Sort key for semantic versions like '0.1.0' -> (0, 1, 0). Falls back
    to the raw string for anything that isn't dot-separated integers."""
    try:
        return tuple(int(part) for part in version_str.split("."))
    except ValueError:
        return (version_str,)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(description="P1-M6 ModelRegistry CLI.")
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument("--register", action="store_true", help="Register a new artifact bundle.")
    action_group.add_argument("--list", action="store_true", help="List all registered versions.")
    action_group.add_argument("--get-latest", action="store_true", help="Print the latest bundle's manifest entry.")
    action_group.add_argument("--get-version", metavar="VERSION", help="Print a specific version's manifest entry.")

    parser.add_argument("--registry-dir", default="model_registry", help="Local registry directory.")
    parser.add_argument("--version", help="Semantic version to register, e.g. 0.1.0 (required with --register).")
    parser.add_argument("--encoder", help="Path to the trained TstccEncoder .pt checkpoint.")
    parser.add_argument("--faiss-index", help="Path PREFIX for the FaissIndexer (no .faiss suffix).")
    parser.add_argument("--config", help="Path to a JSON config file to embed in config_dict.")
    parser.add_argument("--feature-meta", help="Path to a JSON feature_meta file (MUST contain 'vocab_maps').")
    parser.add_argument("--val-loss", type=float, default=float("nan"), help="Validation loss for this checkpoint.")
    parser.add_argument("--use-s3", action="store_true", help="Store the manifest in S3 instead of locally.")
    parser.add_argument("--s3-bucket", help="S3 bucket name (required with --use-s3).")
    parser.add_argument("--s3-prefix", default="", help="S3 key prefix.")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%H:%M:%S")

    args = _build_arg_parser().parse_args()

    registry = ModelRegistry(
        ModelRegistryConfigData(
            registry_dir_str=args.registry_dir,
            use_s3_bool=args.use_s3,
            s3_bucket_str=args.s3_bucket,
            s3_prefix_str=args.s3_prefix,
        )
    )

    if args.register:
        if not (args.version and args.encoder and args.faiss_index):
            raise SystemExit("--register requires --version, --encoder, and --faiss-index.")

        config_dict = load_json_file(args.config) if args.config else {}
        feature_meta_dict = load_json_file(args.feature_meta) if args.feature_meta else {}
        if "vocab_maps" not in feature_meta_dict:
            logger_obj.warning(
                "--feature-meta has no 'vocab_maps' key — ArtifactBundle.load() "
                "will fail later. Pass a feature_meta.json produced by P1-M2's "
                "compute_vocab_sizes()."
            )

        bundle = ArtifactBundle(
            version_str=args.version,
            encoder_path=Path(args.encoder),
            faiss_index_path=Path(args.faiss_index),
            config_dict=config_dict,
            feature_meta_dict=feature_meta_dict,
            time2vec_params_dict={},  # populate separately via extract_time2vec_params() if desired
            val_loss_float=args.val_loss,
        )
        registry.register(bundle)
        print(f"Registered version {args.version}.")

    elif args.list:
        for version_str in registry.list_versions():
            print(version_str)

    elif args.get_latest:
        bundle = registry.get_latest()
        print(json.dumps(bundle.to_manifest_dict(), indent=2, default=str))

    elif args.get_version:
        bundle = registry.get_by_version(args.get_version)
        print(json.dumps(bundle.to_manifest_dict(), indent=2, default=str))


if __name__ == "__main__":
    main()