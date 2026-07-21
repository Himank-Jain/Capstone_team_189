"""
phase2/encoding/reference_encoder_service.py
=================================================
P2-M4  Pretrained Encoder (Reference) — ReferenceEncoderService
CAPSTONE-189

[P2-M4 ReferenceEncoderService]  (primer, Project Directory Structure §6b)
Same TstccEncoder as P2-M3. Encodes last REF_HISTORY_DAYS=90 days per entity.
Produces per-entity centroid_emb (mean of last 30 embs) + emb_variance.
Cold-start fallback: centroid=global_mean, cold_start_flag=True.
Writes EntityProfile to EntityStoreWriter. EMA update: alpha=REF_CENTROID_ALPHA=0.1.

Reuses, does not reimplement
-----------------------------
- InferenceEncoder (P2-M3): same architecture/weights as P2-M3, per the
  planner ("Reuse EncoderInference from P2-M3 — this is the same model
  class, different usage context"). This module never touches
  TstccEncoder.forward() directly.
- RecordEncoder (P2-M2): turns RawRecords into the (numeric, categorical,
  timestamps, lengths) tensors InferenceEncoder expects.

Bridging note: "last 30 embs" vs. the windowed encoder
--------------------------------------------------------
The original planner text predates the Phase 1 event-based redesign and
reads as if one embedding = one raw record. Under the as-built encoder,
one embedding = one seq_len-event WINDOW (default 32 events, see
shared/constants.REF_SEQ_LEN). This module therefore:
  1. Splits an entity's last REF_HISTORY_DAYS of RawRecords into
     consecutive, non-overlapping windows of REF_SEQ_LEN events
     (oldest-first; a short remainder window at the end is kept, not
     dropped, via TstccEncoder's lengths_tensor support).
  2. Encodes each window to one (128,) embedding via InferenceEncoder.
  3. Takes the most recent REF_HISTORY_LEN (=30) window-embeddings as
     "last_N_embeddings" for centroid_emb / emb_variance / history_embs.
This is the only interpretation consistent with both the planner's
intent (a rolling window of *embeddings*, not raw records) and the
as-built P1-M3 architecture that only P1-M3/P2-M3 can actually produce.

Registry-loading note
----------------------
ArtifactBundle.load() (P1-M6) unconditionally also loads a FAISS index
via FaissIndexer.load(), and ArtifactBundle.load_latest() unconditionally
imports ModelRegistry (phase1/registry/model_registry.py). Neither the
FAISS index (P1-M5) nor ModelRegistry exist yet in this handoff, and
P2-M4 does not need either (only P2-M9 needs FAISS). So this module reads
model_registry/artifacts_manifest.json directly and builds just the
encoder, via the SAME build_tstcc_encoder_for_aug_pairs() +
load_weights() + disable_projection() sequence ArtifactBundle.load()
uses internally (kept in lock-step with it — see
_load_inference_encoder_from_manifest() below). Swap this for
ArtifactBundle.load_latest() once P1-M5/P1-M6 are complete; nothing else
in this file would need to change.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch

from phase1.corpus.base_historical_record_provider import BaseHistoricalRecordProvider
from phase1.models.tstcc_encoder import TstccEncoder, build_tstcc_encoder_for_aug_pairs
from phase2.encoding.feature_meta import FeatureMetaStore
from phase2.encoding.inference_encoder import InferenceEncoder
from phase2.encoding.record_encoder import RecordEncoder
from phase2.store.base_entity_store import BaseEntityStoreWriter
from shared.constants import (
    REF_CENTROID_ALPHA,
    REF_DRIFT_ALARM_STD,
    REF_HISTORY_DAYS,
    REF_HISTORY_LEN,
    REF_SEQ_LEN,
)
from shared.types import EntityProfile, RawRecord

logger_obj: logging.Logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Registry loading (see module docstring's "Registry-loading note")
# ─────────────────────────────────────────────────────────────────────────────

def load_inference_encoder_from_manifest(
    manifest_path_str: str = "model_registry/artifacts_manifest.json",
    version_str: Optional[str] = None,
    device_str: Optional[str] = None,
) -> Tuple[InferenceEncoder, FeatureMetaStore]:
    """
    Build a ready-to-use InferenceEncoder (P2-M3) + FeatureMetaStore
    directly from the P1-M6 manifest, without requiring FaissIndexer or
    ModelRegistry to exist. Mirrors ArtifactBundle.load()'s encoder
    construction exactly (same vocab-size derivation, same
    build_tstcc_encoder_for_aug_pairs → load_weights → disable_projection
    sequence) so the two loaders cannot silently diverge.

    Parameters
    ----------
    manifest_path_str:
        Path to artifacts_manifest.json (P1-M6 registry file).
    version_str:
        Specific version to load. Defaults to the highest version_str key
        present (manifest's "versions" dict), i.e. "latest".
    device_str:
        "cuda" / "cpu". Defaults to auto-detect.
    """
    manifest_path = Path(manifest_path_str)
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"[ReferenceEncoderService] Manifest not found: {manifest_path}. "
            f"P1-M6 registry must be built (or point manifest_path_str at "
            f"one) before ReferenceEncoderService can start."
        )

    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest_dict = json.load(fh)

    versions_dict: Dict[str, dict] = manifest_dict["versions"]
    if not versions_dict:
        raise ValueError(f"[ReferenceEncoderService] {manifest_path} has no registered versions")
    chosen_version_str = version_str or max(versions_dict.keys())
    entry_dict = versions_dict[chosen_version_str]

    feature_meta_dict = entry_dict["feature_meta_dict"]
    vocab_maps_dict = feature_meta_dict["vocab_maps"]
    metric_value_stats_raw = feature_meta_dict.get("metric_value_stats", {})
    metric_value_stats_dict = {
        name: (float(stat["mean"]), float(stat["std"])) if isinstance(stat, dict)
        else (float(stat[0]), float(stat[1]))
        for name, stat in metric_value_stats_raw.items()
    }
    feature_meta = FeatureMetaStore.from_dicts(vocab_maps_dict, metric_value_stats_dict)

    device_str = device_str or ("cuda" if torch.cuda.is_available() else "cpu")

    # manifest stores paths with the OS separator of whoever wrote it
    # (observed as Windows "\\"); normalize before resolving.
    encoder_path_str = entry_dict["encoder_path"].replace("\\", "/")
    # Resolve relative to the manifest's own directory, not the CWD, so
    # this works regardless of where the caller's process starts.
    encoder_path = Path(encoder_path_str)
    if not encoder_path.is_absolute():
        encoder_path = manifest_path.parent.parent / encoder_path_str \
            if manifest_path.parent.name != Path(encoder_path_str).parent.name \
            else manifest_path.parent / Path(encoder_path_str).name
    if not encoder_path.exists():
        # last resort: try relative to the manifest's own directory directly
        candidate = manifest_path.parent / Path(encoder_path_str).name
        if candidate.exists():
            encoder_path = candidate
        else:
            raise FileNotFoundError(
                f"[ReferenceEncoderService] Could not resolve encoder_path "
                f"'{entry_dict['encoder_path']}' relative to manifest at {manifest_path}"
            )

    encoder: TstccEncoder = build_tstcc_encoder_for_aug_pairs(
        cloud_vocab_size_int=len(vocab_maps_dict["cloud"]),
        entity_type_vocab_size_int=len(vocab_maps_dict["entity_type"]),
        namespace_vocab_size_int=len(vocab_maps_dict["namespace"]),
        metric_name_vocab_size_int=len(vocab_maps_dict["metric_name"]),
        use_projection_bool=True,  # checkpoint was saved WITH the head; load, then strip
    )
    encoder.load_weights(str(encoder_path), map_location=device_str, strict_bool=True)
    encoder.disable_projection()
    encoder.to(torch.device(device_str))

    inference_encoder = InferenceEncoder(encoder, device=device_str)

    logger_obj.info(
        "[ReferenceEncoderService] Loaded encoder version=%s from %s",
        chosen_version_str, encoder_path,
    )
    return inference_encoder, feature_meta


# ─────────────────────────────────────────────────────────────────────────────
# ReferenceEncoderService
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ReferenceEncoderServiceConfigData:
    """
    Parameters
    ----------
    history_days_int:
        Lookback window when (re)building a profile from scratch.
    history_len_int:
        Max window-embeddings kept per entity (centroid + variance basis,
        and the history_embs list). Older embeddings are dropped once
        this cap is exceeded.
    seq_len_int:
        Events per encoding window — must match the seq_len the encoder
        was trained with (P1-M3 default 32).
    centroid_ema_alpha_float:
        Blend factor for incremental updates:
        new_centroid = alpha * new_emb + (1 - alpha) * old_centroid.
    drift_alarm_std_float:
        Flag an incremental update if the new window-embedding's distance
        from the entity's prior centroid exceeds this many standard
        deviations of that entity's own embedding spread (sqrt(emb_variance)).
    """
    history_days_int: int = REF_HISTORY_DAYS
    history_len_int: int = REF_HISTORY_LEN
    seq_len_int: int = REF_SEQ_LEN
    centroid_ema_alpha_float: float = REF_CENTROID_ALPHA
    drift_alarm_std_float: float = REF_DRIFT_ALARM_STD


class ReferenceEncoderService:
    """
    Builds and maintains per-entity behavioral baselines (EntityProfile)
    by encoding historical records through the same TstccEncoder used at
    P2-M3, and writes them to the entity store.

    Constructor dependencies are all injected (DIP) — this class never
    constructs a corpus reader, an encoder, or a store client itself,
    matching the pattern already established by BatchEncoder /
    InferenceEncoder / RecordEncoder in this codebase.

    Parameters
    ----------
    inference_encoder:
        P2-M3 InferenceEncoder, already loaded (projection stripped,
        eval mode) — e.g. from load_inference_encoder_from_manifest()
        above, or ArtifactBundle.load_latest() once P1-M5/P1-M6 land.
    record_encoder:
        P2-M2 RecordEncoder, constructed with the SAME FeatureMetaStore
        the inference_encoder's checkpoint was trained with. Caller's
        responsibility to keep these paired (see feature_meta.py's own
        CRITICAL note) — this class does not re-validate that.
    historical_record_provider:
        P1-M1 boundary interface — supplies each entity's raw history.
    entity_store_writer:
        P2-M6 boundary interface — where built/updated EntityProfiles are
        written.
    config:
        Tunables; see ReferenceEncoderServiceConfigData.
    global_mean_emb:
        Precomputed corpus-wide mean embedding (128,), L2-normalised,
        used as the cold-start centroid for entities with no history yet.
        If None, cold-start entities get a zero vector instead (still a
        valid fallback — cosine deviation against it is always 1.0 — but
        a real global mean is preferable once available from P1-M5's
        FAISS build).
    """

    def __init__(
        self,
        inference_encoder: InferenceEncoder,
        record_encoder: RecordEncoder,
        historical_record_provider: BaseHistoricalRecordProvider,
        entity_store_writer: BaseEntityStoreWriter,
        config: Optional[ReferenceEncoderServiceConfigData] = None,
        global_mean_emb: Optional[np.ndarray] = None,
    ) -> None:
        self._inference_encoder = inference_encoder
        self._record_encoder = record_encoder
        self._historical_record_provider = historical_record_provider
        self._entity_store_writer = entity_store_writer
        self._config = config or ReferenceEncoderServiceConfigData()
        if global_mean_emb is not None:
            norm = float(np.linalg.norm(global_mean_emb))
            self._global_mean_emb = (
                (global_mean_emb / norm).astype(np.float32) if norm > 0
                else global_mean_emb.astype(np.float32)
            )
        else:
            self._global_mean_emb = np.zeros(128, dtype=np.float32)

    # ── Windowing ────────────────────────────────────────────────────────────

    def _build_windows(self, records: List[RawRecord]) -> List[List[RawRecord]]:
        """
        Split chronologically-sorted records into consecutive,
        non-overlapping windows of self._config.seq_len_int events.
        A trailing short window (fewer than seq_len events) is kept, not
        dropped — TstccEncoder's lengths_tensor masks the padding, so a
        short final window still produces a valid embedding rather than
        losing an entity's most recent behavior.
        """
        seq_len = self._config.seq_len_int
        ordered = sorted(records, key=lambda r: (r.timestamp, r.metric_name))
        return [ordered[i:i + seq_len] for i in range(0, len(ordered), seq_len)] if ordered else []

    def _encode_windows(self, windows: List[List[RawRecord]]) -> np.ndarray:
        """Encode each window to one (128,) embedding, batched through
        InferenceEncoder in a single call. Returns (M, 128) float32."""
        if not windows:
            return np.empty((0, 128), dtype=np.float32)

        encoded_by_window = {
            str(i): self._record_encoder.encode_entity_records(window)
            for i, window in enumerate(windows)
        }
        _, numeric_batch, categorical_batch, timestamps_batch, lengths_batch = (
            RecordEncoder.collate_encoded_batch(encoded_by_window)
        )
        with torch.no_grad():
            emb_tensor = self._inference_encoder.encode(
                numeric_batch, categorical_batch, timestamps_batch, lengths_batch
            )
        return emb_tensor.cpu().numpy().astype(np.float32)

    # ── Centroid / variance ─────────────────────────────────────────────────

    @staticmethod
    def _compute_centroid_and_variance(embs: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        centroid = mean(embs), re-normalised to unit L2 norm (mean of
        unit vectors does not itself lie on the unit sphere).
        variance = trace of the covariance matrix of embs — a single
        scalar spread measure (sum of per-dimension variances).
        """
        centroid = embs.mean(axis=0)
        norm = np.linalg.norm(centroid)
        centroid = centroid / norm if norm > 0 else centroid
        variance = float(np.trace(np.cov(embs, rowvar=False))) if embs.shape[0] > 1 else 0.0
        return centroid.astype(np.float32), variance

    # ── Full (re)build path ─────────────────────────────────────────────────

    def build_profile_for_entity(self, entity_id: str) -> EntityProfile:
        """
        Full (re)build: encode the last history_days_int of entity_id's
        records and produce a fresh EntityProfile from scratch. Used at
        startup and by the periodic (e.g. every 24h) refresh job.
        """
        since_ts = datetime.now(timezone.utc) - timedelta(days=self._config.history_days_int)
        records = self._historical_record_provider.fetch_records_for_entity(entity_id, since_ts)

        if not records:
            profile = EntityProfile(
                entity_id=entity_id,
                centroid_emb=self._global_mean_emb.copy(),
                history_embs=[],
                emb_variance=0.0,
                n_records=0,
                last_update_ts=datetime.now(timezone.utc),
                cold_start_flag=True,
            )
            logger_obj.info("[ReferenceEncoderService] entity_id=%s cold-start (no history)", entity_id)
            return profile

        windows = self._build_windows(records)
        embs = self._encode_windows(windows)
        recent_embs = embs[-self._config.history_len_int:]
        centroid_emb, emb_variance = self._compute_centroid_and_variance(recent_embs)

        profile = EntityProfile(
            entity_id=entity_id,
            centroid_emb=centroid_emb,
            history_embs=list(recent_embs),
            emb_variance=emb_variance,
            n_records=recent_embs.shape[0],
            last_update_ts=datetime.now(timezone.utc),
            cold_start_flag=False,
        )
        return profile

    def build_all_profiles(self) -> None:
        """Startup path: build and write a profile for every entity the
        historical_record_provider currently knows about."""
        entity_ids = self._historical_record_provider.list_known_entity_ids()
        logger_obj.info("[ReferenceEncoderService] Building profiles for %d entities", len(entity_ids))
        for entity_id in entity_ids:
            profile = self.build_profile_for_entity(entity_id)
            self._entity_store_writer.write_entity_profile(profile)

    def refresh_all_entities(self) -> None:
        """
        Periodic full-refresh path (planner: "re-encode new historical
        data every 24h and update centroid"). Intended to be invoked by
        an external scheduler (cron / APScheduler) at that cadence — this
        method itself is just the unit of work, not the scheduler.
        Re-runs the full build (not incremental) so drift in old history
        (e.g. records aging out of the 90-day window) is reflected, not
        just new observations.
        """
        self.build_all_profiles()

    # ── Incremental update path ─────────────────────────────────────────────

    def update_profile_incremental(
        self, entity_id: str, new_records: List[RawRecord]
    ) -> Tuple[EntityProfile, bool]:
        """
        Incremental EMA update: encode ONLY new_records (not the full
        90-day history) and blend into the existing centroid. Falls back
        to a full build_profile_for_entity() if no prior profile exists
        (nothing to blend against yet, or entity_id was cold-started).

        Returns
        -------
        (EntityProfile, drift_alarm_bool)
            drift_alarm_bool is True if the new observation's distance
            from the prior centroid exceeds drift_alarm_std_float
            standard deviations of the entity's own historical spread
            (sqrt(prior emb_variance)). Not stored on EntityProfile
            itself (frozen shared/types.py contract) — caller decides
            what to do with it (e.g. emit a monitoring event).
        """
        prior = self._entity_store_writer.fetch_entity_profile(entity_id)
        if prior is None or prior.cold_start_flag or not new_records:
            profile = self.build_profile_for_entity(entity_id)
            self._entity_store_writer.write_entity_profile(profile)
            return profile, False

        windows = self._build_windows(new_records)
        new_embs = self._encode_windows(windows)
        if new_embs.shape[0] == 0:
            return prior, False

        alpha = self._config.centroid_ema_alpha_float
        drift_alarm = False
        std_dev = float(np.sqrt(max(prior.emb_variance, 0.0)))

        updated_centroid = prior.centroid_emb
        for new_emb in new_embs:
            distance = float(np.linalg.norm(new_emb - updated_centroid))
            if std_dev > 0 and distance > self._config.drift_alarm_std_float * std_dev:
                drift_alarm = True
                logger_obj.warning(
                    "[ReferenceEncoderService] Drift alarm entity_id=%s distance=%.4f "
                    "threshold=%.4f (%.1f std)",
                    entity_id, distance, self._config.drift_alarm_std_float * std_dev,
                    self._config.drift_alarm_std_float,
                )
            updated_centroid = alpha * new_emb + (1.0 - alpha) * updated_centroid
        norm = np.linalg.norm(updated_centroid)
        updated_centroid = (updated_centroid / norm if norm > 0 else updated_centroid).astype(np.float32)

        updated_history = (prior.history_embs + list(new_embs))[-self._config.history_len_int:]
        _, updated_variance = self._compute_centroid_and_variance(np.stack(updated_history))

        profile = EntityProfile(
            entity_id=entity_id,
            centroid_emb=updated_centroid,
            history_embs=updated_history,
            emb_variance=updated_variance,
            n_records=len(updated_history),
            last_update_ts=datetime.now(timezone.utc),
            cold_start_flag=False,
        )
        self._entity_store_writer.write_entity_profile(profile)
        return profile, drift_alarm
