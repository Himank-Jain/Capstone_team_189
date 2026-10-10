"""
phase1/embedding_space/faiss_indexer.py
============================================
P1-M5  Behavioral Embedding Space — FaissIndexer
Unified Predictive Analytics & Intelligent Alerting Platform  |  CAPSTONE-189

[P1-M5 FaissIndexer]  (primer, Project Directory Structure §6b)
Encodes all historical records via BatchEncoder(TstccEncoder). Builds FAISS
IndexIVFFlat(nlist=100). Metadata tagged: entity_id, timestamp, cloud_provider,
severity_label. serialize/load via faiss.write_index/read_index.
Key classes: BatchEncoder, FaissIndexer, EmbeddingVisualiser.

GRASP note (Information Expert): FaissIndexer owns index search because it
holds the FAISS index in memory — matches Section 4 of the Project Directory
Structure doc exactly.

This file owns index construction (build_faiss_index) and the searchable
store (FaissIndexer: add / search_topk / save / load). Offline batch
encoding is a separate concern, owned by batch_encoder.py (SRP).

Consumed by: phase1/train (via scripts/build_faiss_index.py), P1-M6
ArtifactBundle (registers the serialized index path), P2-M9 EpisodeRetriever
(loads FaissIndexer.load(path) at service startup, nprobe=FAISS_N_PROBE).
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import faiss
import numpy as np

try:
    from shared.constants import ENC_EMBED_DIM, FAISS_N_LIST, FAISS_N_PROBE, FAISS_TOP_K
except ImportError:  # shared/ not yet on the path in a standalone checkout
    ENC_EMBED_DIM = 128
    FAISS_N_LIST = 100
    FAISS_N_PROBE = 20
    FAISS_TOP_K = 10

logger_obj: logging.Logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Module-scoped constants
# ─────────────────────────────────────────────────────────────────────────────

FAISS_MIN_TRAIN_POINTS_PER_LIST: int = 39         # Faiss rule-of-thumb: >= 39 pts/cluster
FAISS_DEFAULT_TRAIN_SAMPLE_FRACTION: float = 0.10  # planner: train on ~10% sample
FAISS_METRIC = faiss.METRIC_L2                     # matches TstccEncoder's L2-normalised space


# ─────────────────────────────────────────────────────────────────────────────
# build_faiss_index — index construction + training
# ─────────────────────────────────────────────────────────────────────────────

def build_faiss_index(
    embedding_corpus_array: np.ndarray,
    nlist_int: int = FAISS_N_LIST,
    train_sample_fraction_float: float = FAISS_DEFAULT_TRAIN_SAMPLE_FRACTION,
    random_seed_int: int = 42,
) -> faiss.IndexIVFFlat:
    """
    Build and train a ``faiss.IndexIVFFlat`` over an embedding corpus.

    Per the planner's guidance: an IVF index must be TRAINED before vectors
    are added. Training runs on a random sample (~``train_sample_fraction_float``
    of the corpus, 10% by default) rather than the full corpus, then the full
    corpus is added post-training via ``FaissIndexer.add``.

    Small-corpus safety: Faiss' own rule of thumb wants at least
    ``FAISS_MIN_TRAIN_POINTS_PER_LIST`` (39) training points per cluster.
    Requesting ``nlist_int=FAISS_N_LIST`` (100) against a corpus with, say,
    100 vectors would starve k-means and produce empty/degenerate clusters.
    Rather than let that fail silently at search time, this function clamps
    ``nlist_int`` down to a value the sampled training set can actually
    support and logs a warning — the caller-facing default (100) is
    preserved for the production-scale corpus this module targets.

    Parameters
    ----------
    embedding_corpus_array : np.ndarray
        Shape ``(N, 128)``, dtype float32 (or castable), L2-normalised
        embeddings — typically the output of ``BatchEncoder.encode_records``.
    nlist_int : int
        Requested number of IVF clusters. Defaults to ``FAISS_N_LIST`` (100).
    train_sample_fraction_float : float
        Fraction of the corpus used to train k-means. Defaults to 0.10.
    random_seed_int : int
        Seed for the training-sample draw (reproducibility).

    Returns
    -------
    faiss.IndexIVFFlat
        Trained, empty index (vectors are NOT added here — see
        ``FaissIndexer.add``, which owns population + metadata bookkeeping
        together so they never drift out of sync).

    Raises
    ------
    ValueError
        If the corpus is empty or not 2-D with width ``ENC_EMBED_DIM``.
    """
    if embedding_corpus_array.ndim != 2 or embedding_corpus_array.shape[1] != ENC_EMBED_DIM:
        raise ValueError(
            f"[build_faiss_index] Expected shape (N, {ENC_EMBED_DIM}), "
            f"got {embedding_corpus_array.shape}"
        )

    num_vectors_int: int = embedding_corpus_array.shape[0]
    if num_vectors_int == 0:
        raise ValueError("[build_faiss_index] embedding_corpus_array is empty.")

    embedding_corpus_array = np.ascontiguousarray(embedding_corpus_array, dtype=np.float32)

    # ── Clamp nlist for small corpora ────────────────────────────────────────
    max_supportable_nlist_int: int = max(1, num_vectors_int // FAISS_MIN_TRAIN_POINTS_PER_LIST)
    effective_nlist_int: int = min(nlist_int, max_supportable_nlist_int, num_vectors_int)

    if effective_nlist_int < nlist_int:
        logger_obj.warning(
            "[build_faiss_index] Requested nlist=%d but corpus has only %d vectors; "
            "clamped to nlist=%d to keep >= %d training points/cluster.",
            nlist_int, num_vectors_int, effective_nlist_int, FAISS_MIN_TRAIN_POINTS_PER_LIST,
        )

    # ── Build the sample used for k-means training ───────────────────────────
    rng_obj: np.random.Generator = np.random.default_rng(random_seed_int)
    sample_size_int: int = max(
        effective_nlist_int * FAISS_MIN_TRAIN_POINTS_PER_LIST,
        int(num_vectors_int * train_sample_fraction_float),
    )
    sample_size_int = min(sample_size_int, num_vectors_int)

    train_indices_array: np.ndarray = rng_obj.choice(
        num_vectors_int, size=sample_size_int, replace=False
    )
    train_sample_array: np.ndarray = embedding_corpus_array[train_indices_array]

    # ── Construct + train the index ───────────────────────────────────────────
    quantizer_index: faiss.IndexFlatL2 = faiss.IndexFlatL2(ENC_EMBED_DIM)
    ivf_index: faiss.IndexIVFFlat = faiss.IndexIVFFlat(
        quantizer_index, ENC_EMBED_DIM, effective_nlist_int, FAISS_METRIC
    )

    logger_obj.info(
        "[build_faiss_index] Training IndexIVFFlat: nlist=%d  train_samples=%d/%d",
        effective_nlist_int, sample_size_int, num_vectors_int,
    )
    ivf_index.train(train_sample_array)

    if not ivf_index.is_trained:
        raise RuntimeError("[build_faiss_index] IVF training did not converge.")

    return ivf_index


# ─────────────────────────────────────────────────────────────────────────────
# FaissIndexer — index + metadata, save/load, top-k search
# ─────────────────────────────────────────────────────────────────────────────

class FaissIndexer:
    """
    Wraps a (trained) Faiss index together with parallel record metadata
    (entity_id, timestamp, cloud_provider, severity_label, ...), so the two
    never drift out of sync, and exposes the surface P2-M9 (EpisodeRetriever)
    needs: ``add``, ``search_topk``, ``save``, ``load``.

    GRASP — Information Expert: this class owns index search because it
    holds the FAISS index in memory (Project Directory Structure §4).

    Metadata alignment invariant
    -----------------------------
    ``self.metadata_list[i]`` describes the vector at Faiss internal id ``i``.
    Because vectors are only ever appended (never removed/reordered), a
    returned Faiss index position is always a valid ``metadata_list`` index.

    Parameters
    ----------
    index : faiss.Index
        A (typically already-trained) Faiss index, e.g. from
        :func:`build_faiss_index`.
    nprobe_int : int
        Number of IVF cells to visit per search. Ignored for non-IVF index
        types. Defaults to ``FAISS_N_PROBE`` (20) — the planner explicitly
        flags Faiss' own default of 1 as giving poor recall.
    """

    def __init__(self, index: faiss.Index, nprobe_int: int = FAISS_N_PROBE) -> None:
        self.index: faiss.Index = index
        self.metadata_list: List[Any] = []
        self.nprobe_int: int = nprobe_int
        self._apply_nprobe()

    # ── Public API ────────────────────────────────────────────────────────────

    def add(self, embeddings: np.ndarray, metadata: Sequence[Any]) -> None:
        """
        Add a batch of embeddings and their parallel metadata to the store.

        Parameters
        ----------
        embeddings : np.ndarray
            Shape ``(M, 128)``, dtype castable to float32.
        metadata : Sequence[Any]
            Length ``M``, one entry per embedding row. Per the P1-M5 primer,
            metadata should be tagged with at least entity_id, timestamp,
            cloud_provider, severity_label — any picklable Python object
            (e.g. a dict, or a shared.types dataclass) is accepted.

        Raises
        ------
        ValueError
            If ``embeddings`` and ``metadata`` lengths disagree, or the
            index has not been trained yet (IVF indexes only).
        """
        embeddings = np.ascontiguousarray(embeddings, dtype=np.float32)

        if embeddings.ndim != 2 or embeddings.shape[1] != ENC_EMBED_DIM:
            raise ValueError(
                f"[FaissIndexer.add] Expected shape (M, {ENC_EMBED_DIM}), got {embeddings.shape}"
            )
        if embeddings.shape[0] != len(metadata):
            raise ValueError(
                f"[FaissIndexer.add] embeddings rows ({embeddings.shape[0]}) != "
                f"metadata length ({len(metadata)})"
            )
        if hasattr(self.index, "is_trained") and not self.index.is_trained:
            raise ValueError(
                "[FaissIndexer.add] Index is not trained yet — call "
                "build_faiss_index() (or index.train()) before add()."
            )

        self.index.add(embeddings)
        self.metadata_list.extend(metadata)

        logger_obj.info(
            "[FaissIndexer] Added %d vectors. total=%d", embeddings.shape[0], len(self.metadata_list)
        )

    def search_topk(
        self,
        query_embedding: np.ndarray,
        k: int = FAISS_TOP_K,
    ) -> Tuple[np.ndarray, np.ndarray, List[List[Optional[Any]]]]:
        """
        Retrieve the top-k nearest neighbours for one or more query embeddings.

        Parameters
        ----------
        query_embedding : np.ndarray
            Shape ``(128,)`` for a single query, or ``(Q, 128)`` for a batch.
        k : int
            Number of neighbours to return per query. Defaults to
            ``FAISS_TOP_K`` (10).

        Returns
        -------
        distances : np.ndarray
            Shape ``(Q, k)``. Squared L2 distances (Faiss' native metric for
            L2-normalised vectors — smaller is more similar; convertible to
            cosine similarity via ``sim = 1 - dist / 2``, matching the
            P2-M9 EpisodeRetriever contract).
        indices : np.ndarray
            Shape ``(Q, k)``. Faiss internal ids; ``-1`` marks "no result"
            (can happen if ``k`` exceeds ``ntotal`` or too few IVF cells were
            probed).
        metadata_list : List[List[Any | None]]
            Shape ``(Q, k)`` nested list; ``metadata_list[q][i]`` is the
            metadata for ``indices[q, i]``, or ``None`` where ``indices`` is
            ``-1``.
        """
        query_array: np.ndarray = np.ascontiguousarray(query_embedding, dtype=np.float32)
        if query_array.ndim == 1:
            query_array = query_array.reshape(1, -1)

        if query_array.shape[1] != ENC_EMBED_DIM:
            raise ValueError(
                f"[FaissIndexer.search_topk] Expected width {ENC_EMBED_DIM}, got {query_array.shape[1]}"
            )

        self._apply_nprobe()  # in case nprobe_int was changed after load()/init

        distances_array, indices_array = self.index.search(query_array, k)

        metadata_result_list: List[List[Optional[Any]]] = [
            [
                self.metadata_list[idx_int] if idx_int != -1 else None
                for idx_int in row_indices
            ]
            for row_indices in indices_array
        ]

        return distances_array, indices_array, metadata_result_list

    def save(self, path: str) -> None:
        """
        Persist the index and metadata to disk as two sibling files:
        ``{path}.faiss`` (the Faiss index, via ``faiss.write_index``) and
        ``{path}.meta.pkl`` (metadata_list + nprobe_int, pickled).

        Parameters
        ----------
        path : str
            Destination path prefix. Parent directories are created if
            absent. Typically ``model_registry/behavioral_space`` — the
            resulting ``{path}.faiss`` is what P1-M6 ``ArtifactBundle``
            registers as ``faiss_index_path``.
        """
        dest_path: Path = Path(path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        faiss_path_str: str = str(dest_path) + ".faiss"
        meta_path_str: str = str(dest_path) + ".meta.pkl"

        faiss.write_index(self.index, faiss_path_str)
        with open(meta_path_str, "wb") as meta_file_obj:
            pickle.dump(
                {"metadata_list": self.metadata_list, "nprobe_int": self.nprobe_int},
                meta_file_obj,
            )

        logger_obj.info(
            "[FaissIndexer] Saved → %s (+.meta.pkl)  vectors=%d",
            faiss_path_str, len(self.metadata_list),
        )

    @classmethod
    def load(cls, path: str) -> "FaissIndexer":
        """
        Reconstruct a :class:`FaissIndexer` from files written by :meth:`save`,
        via ``faiss.read_index`` + unpickling the metadata sidecar.

        Parameters
        ----------
        path : str
            Same path prefix passed to :meth:`save` (without ``.faiss`` /
            ``.meta.pkl`` suffixes).

        Returns
        -------
        FaissIndexer
            Fully populated indexer, ready for ``search_topk``. This is the
            call P2-M9 ``EpisodeRetriever`` makes at service startup.

        Raises
        ------
        FileNotFoundError
            If either sibling file is missing.
        """
        faiss_path_str: str = str(path) + ".faiss"

        # Tolerate both naming variants: this class's own "{path}.meta.pkl"
        # (dot-separated, written by save()) and "{path}_meta.pkl"
        # (underscore-separated), since some earlier/parallel scripts in this
        # project wrote the latter. Prefer the dot variant if both exist.
        dot_meta_path_str: str = str(path) + ".meta.pkl"
        underscore_meta_path_str: str = str(path) + "_meta.pkl"
        if Path(dot_meta_path_str).exists():
            meta_path_str: str = dot_meta_path_str
        elif Path(underscore_meta_path_str).exists():
            meta_path_str = underscore_meta_path_str
        else:
            meta_path_str = dot_meta_path_str  # for the error message below

        if not Path(faiss_path_str).exists():
            raise FileNotFoundError(f"[FaissIndexer.load] Missing index file: {faiss_path_str}")
        if not Path(meta_path_str).exists():
            raise FileNotFoundError(
                f"[FaissIndexer.load] Missing metadata file: tried {dot_meta_path_str} "
                f"and {underscore_meta_path_str}"
            )

        loaded_index: faiss.Index = faiss.read_index(faiss_path_str)
        with open(meta_path_str, "rb") as meta_file_obj:
            meta_payload_dict = pickle.load(meta_file_obj)

        indexer_obj: FaissIndexer = cls(
            index=loaded_index,
            nprobe_int=meta_payload_dict.get("nprobe_int", FAISS_N_PROBE),
        )
        indexer_obj.metadata_list = meta_payload_dict["metadata_list"]

        logger_obj.info(
            "[FaissIndexer] Loaded ← %s  vectors=%d", faiss_path_str, len(indexer_obj.metadata_list)
        )

        return indexer_obj

    # ── Private helpers ───────────────────────────────────────────────────────

    def _apply_nprobe(self) -> None:
        """Set nprobe on the wrapped index if it exposes that attribute (IVF-family only)."""
        if hasattr(self.index, "nprobe"):
            self.index.nprobe = self.nprobe_int