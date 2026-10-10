"""
phase1/registry/artifact_bundle.py
=======================================
P1-M6  Outcome / Model Registry — ArtifactBundle
Unified Predictive Analytics & Intelligent Alerting Platform  |  CAPSTONE-189

[P1-M6 ModelRegistry]  (primer, Project Directory Structure §6b)
ArtifactBundle(dataclass): version, encoder_path, faiss_index_path, config,
feature_meta, training_ts, val_loss.
ModelRegistry: register(bundle), get_latest() -> ArtifactBundle, get_by_version(v).
Manifest stored as JSON. ArtifactBundle.load() returns live encoder + FAISS index.
CRITICAL: feature_meta.json must be version-locked with encoder checkpoint.

GRASP note — Information Expert: ArtifactBundle owns load() because it knows
all file paths for the model artifacts (Project Directory Structure §4).

Role suffix note (§2a): "…Bundle: Immutable data container grouping related
artifacts." ArtifactBundle's fields never change after construction; load()
builds and returns fresh live objects each call rather than caching mutable
state on the bundle itself.

Depends on: phase1/models/tstcc_encoder.py (P1-M3), phase1/embedding_space/
faiss_indexer.py (P1-M5). Consumed by: phase1/registry/model_registry.py,
and (cross-phase) P2-M3 InferenceEncoder / P2-M4 ReferenceEncoderService /
P2-M9 EpisodeRetriever, all via ArtifactBundle.load_latest().
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import torch

from phase1.embedding_space.faiss_indexer import FaissIndexer
from phase1.models.tstcc_encoder import TstccEncoder, build_tstcc_encoder_for_aug_pairs

logger_obj: logging.Logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ArtifactBundle — immutable artifact-grouping dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ArtifactBundle:
    """
    Immutable container grouping every artifact produced by one Phase-1
    training run: encoder weights, FAISS index, hyperparameter config,
    feature metadata (vocab + scaler params), and Time2Vec parameters.

    This is the handoff point between Phase 1 and Phase 2 (per the planner):
    P2-M3 / P2-M4 load the encoder from here, P2-M9 loads the FAISS index.

    Parameters
    ----------
    version_str : str
        Semantic version, e.g. ``"0.1.0"`` for the first trained model.
    encoder_path : Path
        Path to a ``.pt`` checkpoint written by
        ``TstccEncoder.save_weights`` / ``save_checkpoint`` (P1-M3/P1-M4).
    faiss_index_path : Path
        Path PREFIX (no ``.faiss`` / ``.meta.pkl`` suffix) passed to
        ``FaissIndexer.save`` / ``FaissIndexer.load`` (P1-M5). e.g.
        ``Path("model_registry/behavioral_space")`` for files
        ``behavioral_space.faiss`` + ``behavioral_space.meta.pkl``.
    config_dict : dict
        Hyperparameters this run used (embed_dim, gru_hidden, thresholds, ...).
        Mirrors ``config/config.yaml``.
    feature_meta_dict : dict
        MUST contain a ``"vocab_maps"`` key with sub-maps for
        ``cloud`` / ``entity_type`` / ``namespace`` / ``metric_name``
        (the exact output of P1-M2's ``compute_vocab_sizes()``), and SHOULD
        contain ``"metric_value_stats"`` (P1-M2's
        ``compute_metric_value_stats()`` output) for inference-time
        z-scoring. CRITICAL (planner): this must be version-locked with the
        encoder checkpoint — vocab sizes determine the encoder's embedding
        table shapes, so a mismatch will fail ``load_weights`` or silently
        produce garbage embeddings.
    time2vec_params_dict : dict
        Learned Time2Vec parameters (linear_w, linear_phi, sine_w, sine_phi),
        extracted via :func:`extract_time2vec_params`. Kept for
        interpretability/debugging; the authoritative copy is already inside
        the encoder's state_dict at ``encoder_path``.
    training_timestamp : datetime
        UTC timestamp of when this checkpoint finished training.
    val_loss_float : float
        Validation loss at the end of training, for comparing versions.
    """
    version_str: str
    encoder_path: Path
    faiss_index_path: Path
    config_dict: Dict[str, Any] = field(default_factory=dict)
    feature_meta_dict: Dict[str, Any] = field(default_factory=dict)
    time2vec_params_dict: Dict[str, Any] = field(default_factory=dict)
    training_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    val_loss_float: float = float("nan")

    # ── Serialization (for the JSON manifest) ────────────────────────────────

    def to_manifest_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dict for storage in artifacts_manifest.json."""
        payload_dict: Dict[str, Any] = asdict(self)
        payload_dict["encoder_path"] = str(self.encoder_path)
        payload_dict["faiss_index_path"] = str(self.faiss_index_path)
        payload_dict["training_timestamp"] = self.training_timestamp.isoformat()
        return payload_dict

    @classmethod
    def from_manifest_dict(cls, payload_dict: Dict[str, Any]) -> "ArtifactBundle":
        """Reconstruct an ArtifactBundle from a manifest entry."""
        return cls(
            version_str=payload_dict["version_str"],
            encoder_path=Path(payload_dict["encoder_path"]),
            faiss_index_path=Path(payload_dict["faiss_index_path"]),
            config_dict=payload_dict.get("config_dict", {}),
            feature_meta_dict=payload_dict.get("feature_meta_dict", {}),
            time2vec_params_dict=payload_dict.get("time2vec_params_dict", {}),
            training_timestamp=datetime.fromisoformat(payload_dict["training_timestamp"]),
            val_loss_float=payload_dict.get("val_loss_float", float("nan")),
        )

    # ── Live artifact loading ────────────────────────────────────────────────

    def load(self, device_str: Optional[str] = None, strict_bool: bool = True) -> Tuple[TstccEncoder, FaissIndexer]:
        """
        Instantiate a live, ready-to-use encoder + FAISS index from this
        bundle's paths and metadata.

        Rebuilds the encoder with vocab sizes read from
        ``feature_meta_dict["vocab_maps"]`` (NOT hardcoded — cardinality is
        data-dependent, per P1-M3), loads ``encoder_path`` weights into it,
        disables the projection head (inference mode), and loads the FAISS
        index + metadata from ``faiss_index_path``.

        Parameters
        ----------
        device_str : str | None
            ``"cuda"`` / ``"cpu"``. Defaults to auto-detect.
        strict_bool : bool
            Forwarded to ``TstccEncoder.load_weights``.

        Returns
        -------
        (TstccEncoder, FaissIndexer)
            Encoder in eval mode with projection disabled, and the loaded
            behavioral-space index — both ready for inference.

        Raises
        ------
        KeyError
            If ``feature_meta_dict`` is missing the required vocab maps
            (this would silently mis-size the encoder otherwise).
        """
        if "vocab_maps" not in self.feature_meta_dict:
            raise KeyError(
                "[ArtifactBundle.load] feature_meta_dict is missing 'vocab_maps' — "
                "cannot reconstruct the encoder with the correct embedding-table "
                "shapes. This bundle's feature_meta.json may not match its encoder_path."
            )

        vocab_maps_dict: Dict[str, Dict[str, int]] = self.feature_meta_dict["vocab_maps"]
        device_str = device_str or ("cuda" if torch.cuda.is_available() else "cpu")

        encoder: TstccEncoder = build_tstcc_encoder_for_aug_pairs(
            cloud_vocab_size_int=len(vocab_maps_dict["cloud"]),
            entity_type_vocab_size_int=len(vocab_maps_dict["entity_type"]),
            namespace_vocab_size_int=len(vocab_maps_dict["namespace"]),
            metric_name_vocab_size_int=len(vocab_maps_dict["metric_name"]),
            use_projection_bool=True,   # load with head present in the checkpoint, then disable
        )
        encoder.load_weights(str(self.encoder_path), map_location=device_str, strict_bool=strict_bool)
        encoder.disable_projection()
        encoder.to(torch.device(device_str))
        encoder.eval()

        faiss_indexer: FaissIndexer = FaissIndexer.load(str(self.faiss_index_path))

        logger_obj.info(
            "[ArtifactBundle.load] version=%s  encoder<-%s  faiss<-%s.faiss",
            self.version_str, self.encoder_path, self.faiss_index_path,
        )

        return encoder, faiss_indexer

    @classmethod
    def load_latest(
        cls,
        registry_dir_str: str = "model_registry",
        device_str: Optional[str] = None,
    ) -> Tuple["ArtifactBundle", TstccEncoder, FaissIndexer]:
        """
        One-command loader (per the planner): find the latest registered
        version and return it fully loaded. This is the call P2-M3 and
        P2-M4 make at service startup to get the encoder, and P2-M9 makes
        to get the FAISS index.

        Parameters
        ----------
        registry_dir_str : str
            Directory containing ``artifacts_manifest.json`` (local mode).
        device_str : str | None
            ``"cuda"`` / ``"cpu"``. Defaults to auto-detect.

        Returns
        -------
        (ArtifactBundle, TstccEncoder, FaissIndexer)
        """
        # Local import to avoid a circular import: model_registry.py imports
        # ArtifactBundle at module scope, so ArtifactBundle cannot import
        # ModelRegistry at module scope in return.
        from phase1.registry.model_registry import ModelRegistry, ModelRegistryConfigData

        registry_obj = ModelRegistry(ModelRegistryConfigData(registry_dir_str=registry_dir_str))
        bundle_obj: ArtifactBundle = registry_obj.get_latest()
        encoder, faiss_indexer = bundle_obj.load(device_str=device_str)
        return bundle_obj, encoder, faiss_indexer


# ─────────────────────────────────────────────────────────────────────────────
# Helper — extract Time2Vec params for the manifest (interpretability only)
# ─────────────────────────────────────────────────────────────────────────────

def extract_time2vec_params(encoder: TstccEncoder) -> Dict[str, Any]:
    """
    Pull the learned Time2Vec parameters out of a trained encoder into a
    plain, JSON-serialisable dict for the manifest's
    ``time2vec_params_dict``.

    The authoritative copy always lives inside the encoder's own
    ``state_dict`` at ``encoder_path`` — this extraction is for
    interpretability / notebooks / quick inspection only, not a load path.

    Parameters
    ----------
    encoder : TstccEncoder
        A (trained) encoder instance.

    Returns
    -------
    dict
        ``{"linear_w": [...], "linear_phi": [...], "sine_w": [...], "sine_phi": [...]}``
    """
    time2vec_module = encoder.time2vec_module
    return {
        "linear_w": time2vec_module.linear_w_param.detach().cpu().tolist(),
        "linear_phi": time2vec_module.linear_phi_param.detach().cpu().tolist(),
        "sine_w": time2vec_module.sine_w_param.detach().cpu().tolist(),
        "sine_phi": time2vec_module.sine_phi_param.detach().cpu().tolist(),
    }


def load_json_file(path_str: str) -> Dict[str, Any]:
    """Small shared helper: load a JSON file into a dict (config.json / feature_meta.json)."""
    with open(path_str, "r") as file_obj:
        return json.load(file_obj)