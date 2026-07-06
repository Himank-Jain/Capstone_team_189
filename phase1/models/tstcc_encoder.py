"""
P1-M3  TstccEncoder — TSTCC Contrastive Sequence Encoder
=========================================================
Unified Predictive Analytics & Intelligent Alerting Platform  |  CAPSTONE-189

Produces 128-d L2-normalised embeddings from variable-length multi-cloud
telemetry sequences.  Used for NT-Xent contrastive pre-training in Phase 1
and loaded directly (projection head stripped) for online inference in Phase 2.

Architecture pipeline
---------------------
    (batch, seq_len, num_numeric + num_categorical + 1 timestamp)
        │
        ▼  EmbeddingLayer
    (batch, seq_len, ENC_FEATURE_DIM=256)       ← concatenate of cat-embeds + numeric-proj
        │
        ▼  Time2Vec(k=8)
    (batch, seq_len, ENC_GRU_INPUT_DIM=264)     ← feature concat with temporal encoding
        │
        ▼  GRU(hidden=128, layers=2, dropout=0.1)
    (batch, seq_len, ENC_GRU_HIDDEN=128)
        │
        ▼  AttentionPooling
    (batch, ENC_GRU_HIDDEN=128)
        │
        ▼  ProjectionHead  [training ONLY — bypassed at inference]
    (batch, ENC_EMBED_DIM=128)
        │
        ▼  F.normalize(p=2, dim=-1)
    (batch, ENC_EMBED_DIM=128)  ◄── L2-normalised contract embedding

Integration contracts (all payloads via shared/types.py)
---------------------------------------------------------
  ➜ P1-M4  NTXentLossComputer   : receives embedding pairs (z_i, z_j) from
                                   two augmented views of the same sequence.
  ➜ P2-M3  InferenceEncoderSvc  : loads checkpoint with load_weights(); sets
                                   use_projection_bool=False before inference.
  ➜ P2-M4  ReferenceManager     : loads same weights to build entity baselines.
  ➜ P2-M5  CurrentEmbeddingPipe : consumes normalised embedding output.

Naming conventions  (CAPSTONE-189)
-----------------------------------
  Classes   : PascalCase + RoleSuffix         e.g. EmbeddingLayer, AttentionPooling
  Functions : snake_case + ActionPrefix        e.g. forward, save_weights
  Variables : snake_case + TypeSuffix          e.g. hidden_dim_int, embed_dim_int
  Constants : UPPER_SNAKE + ModulePrefix (ENC_) e.g. ENC_GRU_HIDDEN, ENC_EMBED_DIM
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

logger_obj: logging.Logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Module-scoped constants  (prefix: ENC_)
# ─────────────────────────────────────────────────────────────────────────────

ENC_FEATURE_DIM: int        = 256   # EmbeddingLayer output width (input to GRU pipeline)
ENC_TIME2VEC_K: int         = 8     # Time2Vec total output (1 linear + 7 sine terms)
ENC_GRU_INPUT_DIM: int      = ENC_FEATURE_DIM + ENC_TIME2VEC_K  # = 264
ENC_GRU_HIDDEN: int         = 128   # GRU hidden-state width
ENC_GRU_LAYERS: int         = 2     # stacked GRU layers
ENC_GRU_DROPOUT: float      = 0.1   # inter-layer GRU dropout (only active when layers ≥ 2)
ENC_EMBED_DIM: int          = 128   # final L2-normalised embedding dimension
ENC_PROJ_HIDDEN: int        = 128   # ProjectionHead intermediate dimension
ENC_CHECKPOINT_FREQ: int    = 5     # save a checkpoint every N training epochs
ENC_MODEL_REGISTRY_DIR: str = "model_registry"  # default checkpoint output folder


# ─────────────────────────────────────────────────────────────────────────────
# Configuration dataclasses  (mirror config/config.yaml §encoder)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CategoricalFieldConfigData:
    """
    Per-column specification for a single categorical input feature.

    Parameters
    ----------
    field_name_str:
        Human-readable column label used in log messages.
    vocab_size_int:
        Total vocabulary cardinality **including** reserved indices.
        Convention: index 0 is ``<PAD>/<UNK>`` (gradient is zeroed).
    embed_dim_int:
        Embedding projection dimension for this column.
        Typical rule-of-thumb: ``min(vocab_size // 2, 50)``.
    padding_idx_int:
        Vocabulary index whose gradient is zeroed during back-prop. Default 0.
    """
    field_name_str: str
    vocab_size_int: int
    embed_dim_int: int
    padding_idx_int: int = 0


@dataclass
class EmbeddingLayerConfigData:
    """
    Full configuration for :class:`EmbeddingLayer`.

    Parameters
    ----------
    categorical_fields_list:
        Ordered list of :class:`CategoricalFieldConfigData`, one per
        categorical column.  Column order **must** match the last dim of
        ``categorical_input_tensor`` passed to ``forward()``.
    num_numeric_int:
        Count of continuous float features in the numeric input tensor.
    output_dim_int:
        Target dimension after projecting the concatenated embeddings.
        **Must equal** ``ENC_FEATURE_DIM`` (256) for GRU pipeline compatibility.
    numeric_proj_dim_int:
        Hidden width of the numeric sub-projection before concatenation.
        Defaults to ``output_dim_int // 2`` (128) so numeric and categorical
        halves contribute roughly equally.
    """
    categorical_fields_list: List[CategoricalFieldConfigData] = field(default_factory=list)
    num_numeric_int: int = 0
    output_dim_int: int = ENC_FEATURE_DIM
    numeric_proj_dim_int: int = ENC_FEATURE_DIM // 2   # = 128


@dataclass
class TstccEncoderConfigData:
    """
    Top-level configuration for :class:`TstccEncoder`.

    Mirrors the ``encoder`` section of ``config/config.yaml``.

    Parameters
    ----------
    embedding_cfg:
        Sub-config forwarded to :class:`EmbeddingLayer`.
    time2vec_k_int:
        Total Time2Vec output size (1 linear + ``k-1`` sine terms).
    gru_hidden_int:
        GRU hidden-state width.
    gru_layers_int:
        Number of stacked GRU layers.  Must be ≥ 2 for dropout to apply.
    gru_dropout_float:
        Dropout probability applied **between** GRU layers (ignored if
        ``gru_layers_int`` == 1).
    embed_dim_int:
        Dimensionality of the final L2-normalised output embedding.
    proj_hidden_int:
        :class:`ProjectionHead` intermediate width.
    use_projection_bool:
        Set ``False`` in Phase-2 inference to bypass the projection head,
        exposing the 128-d GRU representation directly.
    checkpoint_dir_str:
        Directory path where periodic checkpoints are persisted.
    """
    embedding_cfg: EmbeddingLayerConfigData = field(default_factory=EmbeddingLayerConfigData)
    time2vec_k_int: int = ENC_TIME2VEC_K
    gru_hidden_int: int = ENC_GRU_HIDDEN
    gru_layers_int: int = ENC_GRU_LAYERS
    gru_dropout_float: float = ENC_GRU_DROPOUT
    embed_dim_int: int = ENC_EMBED_DIM
    proj_hidden_int: int = ENC_PROJ_HIDDEN
    use_projection_bool: bool = True
    checkpoint_dir_str: str = ENC_MODEL_REGISTRY_DIR


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — EmbeddingLayer
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddingLayer(nn.Module):
    """
    Converts raw mixed inputs (categorical indices + numeric floats) into a
    single dense feature tensor of shape ``(batch, seq_len, output_dim)``.

    Design decisions
    ----------------
    * One ``nn.Embedding`` per categorical column so each field gets its own
      independent learnable lookup table.  Columns with small vocabularies
      (e.g. cloud_provider ∈ {AWS, Azure, GCP, OCI}) stay compact.
    * Numeric features pass through ``nn.Linear → LayerNorm`` before being
      concatenated with categorical embeddings.  This projects them into a
      comparable magnitude and scale.
    * A final ``nn.Linear → LayerNorm`` projects the concatenation to
      ``output_dim`` (ENC_FEATURE_DIM = 256).

    SRP note: This class owns *only* feature encoding.  Temporal encoding
    (timestamps) is handled by :class:`Time2Vec`.

    DIP note: Receives ``EmbeddingLayerConfigData`` via constructor; callers
    inject the config rather than this class reading config.yaml directly.

    Parameters
    ----------
    config : EmbeddingLayerConfigData
        Embedding configuration (vocab sizes, embed dims, numeric count, etc.).

    Raises
    ------
    ValueError
        If both ``categorical_fields_list`` is empty and ``num_numeric_int``
        is 0 — no input features are defined.
    """

    def __init__(self, config: EmbeddingLayerConfigData) -> None:
        super().__init__()

        has_categorical_bool: bool = bool(config.categorical_fields_list)
        has_numeric_bool: bool     = config.num_numeric_int > 0

        if not has_categorical_bool and not has_numeric_bool:
            raise ValueError(
                "[EmbeddingLayer] Config must define at least one categorical "
                "field or numeric feature."
            )

        self._config_data: EmbeddingLayerConfigData = config

        # ── Categorical sub-module: one nn.Embedding per column ──────────────
        self.cat_embed_module_list: nn.ModuleList = nn.ModuleList([
            nn.Embedding(
                num_embeddings=f.vocab_size_int,
                embedding_dim=f.embed_dim_int,
                padding_idx=f.padding_idx_int,
            )
            for f in config.categorical_fields_list
        ])

        cat_total_dim_int: int = sum(f.embed_dim_int for f in config.categorical_fields_list)

        # ── Numeric sub-module: single linear projection + LayerNorm ─────────
        self._has_numeric_bool: bool = has_numeric_bool
        numeric_out_dim_int: int = 0

        if has_numeric_bool:
            numeric_out_dim_int = config.numeric_proj_dim_int
            self.numeric_proj_layer: nn.Linear    = nn.Linear(config.num_numeric_int, numeric_out_dim_int)
            self.numeric_norm_layer: nn.LayerNorm = nn.LayerNorm(numeric_out_dim_int)

        # ── Final fusion projection ───────────────────────────────────────────
        concat_dim_int: int = cat_total_dim_int + numeric_out_dim_int
        self.output_proj_layer: nn.Linear    = nn.Linear(concat_dim_int, config.output_dim_int)
        self.output_norm_layer: nn.LayerNorm = nn.LayerNorm(config.output_dim_int)

        logger_obj.debug(
            "[EmbeddingLayer] cat_dim=%d  numeric_dim=%d  concat_dim=%d  output_dim=%d",
            cat_total_dim_int, numeric_out_dim_int, concat_dim_int, config.output_dim_int,
        )

    # ── forward ──────────────────────────────────────────────────────────────

    def forward(
        self,
        numeric_input_tensor: torch.Tensor,
        categorical_input_tensor: torch.Tensor,
    ) -> torch.Tensor:
        """
        Encode mixed raw features into a fixed-width dense representation.

        Parameters
        ----------
        numeric_input_tensor : Tensor
            Shape ``(batch, seq_len, num_numeric)``.
            Pass an empty tensor (num_numeric=0) if there are no numeric fields.
        categorical_input_tensor : Tensor
            Shape ``(batch, seq_len, num_categorical_fields)``.
            Values are integer vocabulary indices; dtype should be
            ``torch.long``.  Each column ``[..., i]`` is fed into
            ``cat_embed_module_list[i]``.

        Returns
        -------
        Tensor
            Shape ``(batch, seq_len, output_dim)``; LayerNorm-normalised,
            ready to be concatenated with Time2Vec output.
        """
        parts_list: List[torch.Tensor] = []

        # Embed each categorical column independently
        for col_idx_int, emb_layer in enumerate(self.cat_embed_module_list):
            col_indices_tensor: torch.Tensor = categorical_input_tensor[..., col_idx_int].long()
            parts_list.append(emb_layer(col_indices_tensor))  # (batch, seq_len, embed_dim_i)

        # Project numeric features into shared space
        if self._has_numeric_bool:
            numeric_proj_tensor: torch.Tensor = self.numeric_norm_layer(
                self.numeric_proj_layer(numeric_input_tensor)
            )  # (batch, seq_len, numeric_proj_dim)
            parts_list.append(numeric_proj_tensor)

        # Concatenate all parts and project to output_dim
        concat_tensor: torch.Tensor = torch.cat(parts_list, dim=-1)   # (batch, seq_len, concat_dim)
        output_tensor: torch.Tensor = self.output_norm_layer(
            self.output_proj_layer(concat_tensor)
        )  # (batch, seq_len, output_dim)

        return output_tensor


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — Time2Vec
# ─────────────────────────────────────────────────────────────────────────────

class Time2Vec(nn.Module):
    """
    Learnable periodic timestamp encoding from Kazemi et al. (2019).

    For a scalar (normalised) timestamp τ per timestep:

        t2v(τ)[0]   = ω₀ · τ + φ₀              (linear trend term)
        t2v(τ)[i]   = sin(ωᵢ · τ + φᵢ)  ∀ i ∈ [1, k-1]  (sinusoidal terms)

    Concatenated into a k-dimensional vector (k = ENC_TIME2VEC_K = 8).
    This vector is concatenated with the EmbeddingLayer output to form the
    GRU input: (256 + 8 = 264).

    Initialisation note
    -------------------
    ``ωᵢ`` (sine frequencies) use **small Gaussian initialisation** (σ=0.01)
    rather than uniform random.  Uniform init can produce high initial
    frequencies that escape the sine's gradient region early in training,
    causing the periodic terms to deactivate.  Small Gaussian keeps all
    frequencies near zero initially, letting the model discover useful periods
    through gradient descent.

    Parameters
    ----------
    k_int : int
        Total output size.  Must be ≥ 2 (at least 1 linear + 1 sine).
        Defaults to ``ENC_TIME2VEC_K`` = 8.
    """

    def __init__(self, k_int: int = ENC_TIME2VEC_K) -> None:
        super().__init__()

        if k_int < 2:
            raise ValueError(f"[Time2Vec] k_int must be ≥ 2, got {k_int}")

        self.k_int: int = k_int
        num_sine_int: int = k_int - 1  # = 7 for k=8

        # Linear trend term  (ω₀, φ₀)
        self.linear_w_param: nn.Parameter  = nn.Parameter(torch.randn(1) * 0.01)
        self.linear_phi_param: nn.Parameter = nn.Parameter(torch.zeros(1))

        # Sine frequency and phase parameters  (ωᵢ, φᵢ for i=1..k-1)
        # CRITICAL: Small Gaussian init (σ=0.01) — NOT uniform.
        # Uniform init with large range forces high initial frequencies that
        # kill gradients via the flat regions of sin().
        self.sine_w_param: nn.Parameter   = nn.Parameter(torch.randn(num_sine_int) * 0.01)
        self.sine_phi_param: nn.Parameter = nn.Parameter(torch.zeros(num_sine_int))

    def forward(self, tau_tensor: torch.Tensor) -> torch.Tensor:
        """
        Compute Time2Vec encoding for a batch of timestamp sequences.

        Parameters
        ----------
        tau_tensor : Tensor
            Normalised timestamps, shape ``(batch, seq_len, 1)``.
            Should be min-max or z-score normalised before passing in.

        Returns
        -------
        Tensor
            Shape ``(batch, seq_len, k)`` — the temporal encoding ready to
            be concatenated with the EmbeddingLayer output tensor.
        """
        # Linear term:  (batch, seq_len, 1)
        linear_term_tensor: torch.Tensor = (
            self.linear_w_param * tau_tensor + self.linear_phi_param
        )

        # Sine terms:   broadcast tau over k-1 frequencies → (batch, seq_len, k-1)
        # tau_tensor shape: (batch, seq_len, 1) broadcasts with sine_w (k-1,)
        sine_terms_tensor: torch.Tensor = torch.sin(
            self.sine_w_param * tau_tensor + self.sine_phi_param
        )

        # Concatenate along last dim → (batch, seq_len, k)
        return torch.cat([linear_term_tensor, sine_terms_tensor], dim=-1)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 4 — AttentionPooling
# ─────────────────────────────────────────────────────────────────────────────

class AttentionPooling(nn.Module):
    """
    Single-head additive attention that collapses a sequence of GRU hidden
    states into a single context vector.

    Mechanism
    ---------
    1. Project each hidden state:  ``e = tanh(W · h)``
    2. Compute scalar score:        ``α_raw = q · e``        (dot with learned query)
    3. Mask padding positions:      ``α_raw[pad] = -∞``
    4. Normalise:                   ``α = softmax(α_raw)``
    5. Weighted sum:                ``c = Σ αₜ · hₜ``

    This formulation (sometimes called Bahdanau-style single-query attention)
    is preferred over simple last-state pooling because it learns *which*
    timesteps carry the most anomaly-relevant signal, making the final
    embedding more robust to sequence length variation.

    Parameters
    ----------
    hidden_dim_int : int
        Width of the GRU hidden states being pooled. Default ENC_GRU_HIDDEN=128.
    """

    def __init__(self, hidden_dim_int: int = ENC_GRU_HIDDEN) -> None:
        super().__init__()

        self.hidden_dim_int: int = hidden_dim_int

        # Learnable projection matrix  W  (hidden_dim → hidden_dim)
        self.proj_layer: nn.Linear = nn.Linear(hidden_dim_int, hidden_dim_int, bias=True)

        # Learnable query vector  q  (hidden_dim,)
        self.query_param: nn.Parameter = nn.Parameter(torch.randn(hidden_dim_int) * 0.01)

    def forward(
        self,
        hidden_states_tensor: torch.Tensor,
        valid_mask_tensor: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        Pool GRU hidden states into a single context vector.

        Parameters
        ----------
        hidden_states_tensor : Tensor
            GRU output, shape ``(batch, seq_len, hidden_dim)``.
        valid_mask_tensor : Tensor | None
            Boolean mask, shape ``(batch, seq_len)``.
            ``True`` = valid timestep, ``False`` = padding.
            When ``None``, all positions are treated as valid.

        Returns
        -------
        Tensor
            Context vector, shape ``(batch, hidden_dim)``.
        """
        # Step 1: Project and squash  → (batch, seq_len, hidden_dim)
        projected_tensor: torch.Tensor = torch.tanh(self.proj_layer(hidden_states_tensor))

        # Step 2: Dot with query  → (batch, seq_len)
        # einsum: for each batch b and time t, sum over hidden dim h
        scores_tensor: torch.Tensor = torch.einsum(
            "bth,h->bt", projected_tensor, self.query_param
        )

        # Step 3: Mask padding positions with -inf so softmax drives them to 0
        if valid_mask_tensor is not None:
            scores_tensor = scores_tensor.masked_fill(~valid_mask_tensor, float("-inf"))

        # Step 4: Normalised attention weights  → (batch, seq_len)
        attn_weights_tensor: torch.Tensor = torch.softmax(scores_tensor, dim=-1)

        # Guard against NaN when an entire sequence is masked (shouldn't happen
        # in practice but protects against edge cases in batch construction).
        attn_weights_tensor = torch.nan_to_num(attn_weights_tensor, nan=0.0)

        # Step 5: Weighted sum  → (batch, hidden_dim)
        context_tensor: torch.Tensor = torch.einsum(
            "bt,bth->bh", attn_weights_tensor, hidden_states_tensor
        )

        return context_tensor


# ─────────────────────────────────────────────────────────────────────────────
# Layer 5 — ProjectionHead
# ─────────────────────────────────────────────────────────────────────────────

class ProjectionHead(nn.Module):
    """
    Two-layer MLP that maps the pooled GRU representation into the
    contrastive embedding space used by NT-Xent loss (P1-M4).

    Architecture:   Linear(128→128) → ReLU → Linear(128→128)

    Stripping convention
    --------------------
    This module is **only active during contrastive pre-training**.  At
    inference time (P2-M3, P2-M4) ``TstccEncoder`` bypasses this head and
    exposes the AttentionPooling output directly.  This is the standard
    SimCLR/MoCo practice: the projection head improves contrastive loss
    optimisation without contaminating the representation quality.

    The L2 normalisation that follows the head lives in
    ``TstccEncoder.forward()`` so it applies to both training and inference
    outputs consistently.

    Parameters
    ----------
    input_dim_int : int
        Input width (matches ENC_GRU_HIDDEN = 128).
    hidden_dim_int : int
        Intermediate width.
    output_dim_int : int
        Output width (matches ENC_EMBED_DIM = 128).
    """

    def __init__(
        self,
        input_dim_int: int  = ENC_GRU_HIDDEN,
        hidden_dim_int: int = ENC_PROJ_HIDDEN,
        output_dim_int: int = ENC_EMBED_DIM,
    ) -> None:
        super().__init__()

        self.mlp_module: nn.Sequential = nn.Sequential(
            nn.Linear(input_dim_int, hidden_dim_int),
            nn.ReLU(inplace=True),
            nn.Linear(hidden_dim_int, output_dim_int),
            # NOTE: NO activation after the last Linear.
            # L2 normalisation is applied in TstccEncoder.forward() so that
            # it is always applied regardless of whether the head is active.
        )

    def forward(self, context_tensor: torch.Tensor) -> torch.Tensor:
        """
        Project context vector into contrastive embedding space.

        Parameters
        ----------
        context_tensor : Tensor
            Shape ``(batch, input_dim)``.

        Returns
        -------
        Tensor
            Shape ``(batch, output_dim)`` — **not yet L2-normalised**.
            Normalisation is done in :meth:`TstccEncoder.forward`.
        """
        return self.mlp_module(context_tensor)


# ─────────────────────────────────────────────────────────────────────────────
# Main module — TstccEncoder
# ─────────────────────────────────────────────────────────────────────────────

class TstccEncoder(nn.Module):
    """
    Full TSTCC contrastive sequence encoder (P1-M3).

    Orchestrates the five sub-layers:
        EmbeddingLayer → Time2Vec → GRU → AttentionPooling → ProjectionHead

    The final output is always **L2-normalised** to the unit hypersphere so
    cosine similarity equals the dot product, a requirement for NT-Xent loss.

    Variable-length sequences
    -------------------------
    The GRU sub-module uses ``pack_padded_sequence`` / ``pad_packed_sequence``
    when ``lengths_tensor`` is supplied.  This ensures:
      * Padded positions do not contribute to GRU hidden state updates.
      * AttentionPooling receives a boolean mask to ignore padded timesteps.
    Always pass ``lengths_tensor`` during training for correctness; it may be
    omitted only when all sequences in the batch share the same length.

    Projection head toggle
    ----------------------
    Set ``use_projection_bool=False`` (or call :meth:`disable_projection`) when
    loading the encoder for Phase-2 inference.  The head weights are **retained**
    in the checkpoint so a single file works for both training and inference.

    Parameters
    ----------
    config : TstccEncoderConfigData
        Full encoder configuration (DIP: injected, not read directly).
    embedding_layer : EmbeddingLayer
        Pre-constructed EmbeddingLayer.  Injected to allow unit-testing each
        sub-module independently (ISP / DIP).

    Examples
    --------
    >>> cfg = TstccEncoderConfigData(...)
    >>> emb = EmbeddingLayer(cfg.embedding_cfg)
    >>> enc = TstccEncoder(cfg, emb)
    >>> z = enc(numeric, categorical, timestamps, lengths)
    >>> assert z.shape == (batch, 128) and torch.allclose(z.norm(dim=-1), torch.ones(batch))
    """

    def __init__(
        self,
        config: TstccEncoderConfigData,
        embedding_layer: EmbeddingLayer,
    ) -> None:
        super().__init__()

        self._config_data: TstccEncoderConfigData = config

        # ── Sub-layers (injected or constructed here) ─────────────────────────

        # Layer 1: Feature encoding (injected — allows mock/swap in tests)
        self.embedding_layer_module: EmbeddingLayer = embedding_layer

        # Layer 2: Temporal encoding
        self.time2vec_module: Time2Vec = Time2Vec(k_int=config.time2vec_k_int)

        # Layer 3: Sequence encoder
        gru_input_dim_int: int = config.embedding_cfg.output_dim_int + config.time2vec_k_int
        self.gru_module: nn.GRU = nn.GRU(
            input_size=gru_input_dim_int,
            hidden_size=config.gru_hidden_int,
            num_layers=config.gru_layers_int,
            batch_first=True,
            dropout=config.gru_dropout_float if config.gru_layers_int > 1 else 0.0,
            bidirectional=False,
        )

        # Layer 4: Sequence-to-vector
        self.attention_pooling_module: AttentionPooling = AttentionPooling(
            hidden_dim_int=config.gru_hidden_int
        )

        # Layer 5: Contrastive projection (training only)
        self.projection_head_module: ProjectionHead = ProjectionHead(
            input_dim_int=config.gru_hidden_int,
            hidden_dim_int=config.proj_hidden_int,
            output_dim_int=config.embed_dim_int,
        )

        # Runtime flag — toggled by callers at inference time
        self.use_projection_bool: bool = config.use_projection_bool

        logger_obj.info(
            "[TstccEncoder] Initialised.  gru_input=%d  gru_hidden=%d  "
            "embed_dim=%d  projection=%s",
            gru_input_dim_int,
            config.gru_hidden_int,
            config.embed_dim_int,
            "ON" if self.use_projection_bool else "OFF",
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def forward(
        self,
        numeric_input_tensor: torch.Tensor,
        categorical_input_tensor: torch.Tensor,
        timestamps_tensor: torch.Tensor,
        lengths_tensor: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        Encode a batch of telemetry sequences into L2-normalised embeddings.

        Parameters
        ----------
        numeric_input_tensor : Tensor
            Continuous features.  Shape ``(batch, seq_len, num_numeric)``.
        categorical_input_tensor : Tensor
            Integer-encoded categoricals.
            Shape ``(batch, seq_len, num_categorical_fields)``.
        timestamps_tensor : Tensor
            Normalised timestamps (float).  Shape ``(batch, seq_len, 1)``.
            Should be min-max or z-score normalised to keep Time2Vec stable.
        lengths_tensor : Tensor | None
            True (non-padded) length of each sequence in the batch.
            Shape ``(batch,)``, dtype ``torch.long``.
            Pass ``None`` only when all sequences share the same length.

        Returns
        -------
        Tensor
            L2-normalised embeddings.  Shape ``(batch, embed_dim=128)``.
            Every row lies on the unit sphere: ``||z||₂ = 1``.
        """
        batch_size_int: int = numeric_input_tensor.size(0)

        # ── Step 1: Feature embedding  ────────────────────────────────────────
        # (batch, seq_len, num_numeric+num_cat) → (batch, seq_len, ENC_FEATURE_DIM=256)
        features_tensor: torch.Tensor = self.embedding_layer_module(
            numeric_input_tensor, categorical_input_tensor
        )

        # ── Step 2: Temporal encoding  ────────────────────────────────────────
        # timestamps: (batch, seq_len, 1) → time_enc: (batch, seq_len, k=8)
        time_enc_tensor: torch.Tensor = self.time2vec_module(timestamps_tensor)

        # ── Step 3: Concatenate features + temporal encoding  ─────────────────
        # (batch, seq_len, 256) ‖ (batch, seq_len, 8) = (batch, seq_len, 264)
        gru_input_tensor: torch.Tensor = torch.cat([features_tensor, time_enc_tensor], dim=-1)

        # ── Step 4: GRU with variable-length sequence support  ────────────────
        gru_output_tensor, valid_mask_tensor = self._run_gru(
            gru_input_tensor, lengths_tensor
        )
        # gru_output_tensor: (batch, seq_len, ENC_GRU_HIDDEN=128)
        # valid_mask_tensor: (batch, seq_len) bool | None

        # ── Step 5: Attention pooling  ────────────────────────────────────────
        # (batch, seq_len, 128) → (batch, 128)
        context_tensor: torch.Tensor = self.attention_pooling_module(
            gru_output_tensor, valid_mask_tensor
        )

        # ── Step 6: (Optionally) project into contrastive space  ──────────────
        if self.use_projection_bool:
            context_tensor = self.projection_head_module(context_tensor)
            # (batch, 128) → (batch, 128)

        # ── Step 7: L2 normalise — ALWAYS applied, regardless of head state ───
        # This is the contract: all outputs lie on the unit hypersphere.
        embedding_tensor: torch.Tensor = F.normalize(context_tensor, p=2, dim=-1)
        # (batch, ENC_EMBED_DIM=128)

        return embedding_tensor

    def encode_without_projection(
        self,
        numeric_input_tensor: torch.Tensor,
        categorical_input_tensor: torch.Tensor,
        timestamps_tensor: torch.Tensor,
        lengths_tensor: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        Convenience wrapper for Phase-2 inference: bypasses the projection
        head and returns the L2-normalised AttentionPooling output.

        Called by P2-M3 (InferenceEncoderSvc) and P2-M4 (ReferenceManager).
        Does NOT permanently alter ``use_projection_bool``; the flag is
        restored after the forward pass.

        Parameters
        ----------
        (same as :meth:`forward`)

        Returns
        -------
        Tensor
            L2-normalised representation, shape ``(batch, 128)``.
        """
        prev_projection_bool: bool = self.use_projection_bool
        self.use_projection_bool = False
        try:
            with torch.no_grad():
                embedding_tensor: torch.Tensor = self.forward(
                    numeric_input_tensor,
                    categorical_input_tensor,
                    timestamps_tensor,
                    lengths_tensor,
                )
        finally:
            self.use_projection_bool = prev_projection_bool   # always restore

        return embedding_tensor

    def disable_projection(self) -> None:
        """
        Permanently disable the projection head for this instance.

        Typically called once after :meth:`load_weights` in inference services.
        The head weights remain in memory (enabling round-trip serialisation)
        but are skipped in :meth:`forward`.
        """
        self.use_projection_bool = False
        logger_obj.info("[TstccEncoder] Projection head disabled (inference mode).")

    def enable_projection(self) -> None:
        """Re-enable the projection head (e.g. when resuming training)."""
        self.use_projection_bool = True
        logger_obj.info("[TstccEncoder] Projection head enabled (training mode).")

    # ── Checkpointing ─────────────────────────────────────────────────────────

    def save_weights(self, path_str: str) -> None:
        """
        Persist model weights and configuration to disk.

        Saves the full ``state_dict`` including the projection head so that
        the same file can be loaded for both continued training and inference.

        Parameters
        ----------
        path_str : str
            Destination file path.  Parent directories are created if absent.
        """
        dest_path: Path = Path(path_str)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        payload_dict: Dict = {
            "state_dict":           self.state_dict(),
            "use_projection_bool":  self.use_projection_bool,
            "embed_dim_int":        self._config_data.embed_dim_int,
            "gru_hidden_int":       self._config_data.gru_hidden_int,
        }

        torch.save(payload_dict, str(dest_path))
        logger_obj.info("[TstccEncoder] Weights saved → %s", dest_path)

    def load_weights(
        self,
        path_str: str,
        map_location: Optional[str] = None,
        strict_bool: bool = True,
    ) -> None:
        """
        Load model weights from a checkpoint produced by :meth:`save_weights`
        or :meth:`save_checkpoint`.

        Parameters
        ----------
        path_str : str
            Source checkpoint file path.
        map_location : str | None
            Device string passed to ``torch.load`` (e.g. ``"cpu"``).
            Pass ``None`` to load to the same device the weights were saved from.
        strict_bool : bool
            If ``True`` (default), all keys in the checkpoint must match.
            Set ``False`` when loading weights from a different architecture
            variant (e.g. pretrained on AWS only, fine-tuning on all clouds).

        Raises
        ------
        FileNotFoundError
            If ``path_str`` does not exist.
        RuntimeError
            If ``strict_bool=True`` and the state dict keys do not match.
        """
        source_path: Path = Path(path_str)
        if not source_path.exists():
            raise FileNotFoundError(f"[TstccEncoder] Checkpoint not found: {source_path}")

        checkpoint_dict: Dict = torch.load(str(source_path), map_location=map_location)

        # Support both bare state_dict files and our enriched checkpoint format
        state_dict_to_load = (
            checkpoint_dict.get("state_dict", checkpoint_dict)
            if isinstance(checkpoint_dict, dict) and "state_dict" in checkpoint_dict
            else checkpoint_dict
        )

        self.load_state_dict(state_dict_to_load, strict=strict_bool)
        logger_obj.info(
            "[TstccEncoder] Weights loaded ← %s  (strict=%s)", source_path, strict_bool
        )

    def save_checkpoint(
        self,
        epoch_int: int,
        optimizer_state_dict: Optional[Dict] = None,
        loss_float: Optional[float] = None,
    ) -> str:
        """
        Persist a training checkpoint to ``model_registry/``.

        Called by the training loop every ``ENC_CHECKPOINT_FREQ`` epochs.
        The caller is responsible for checking the epoch frequency:

            >>> if epoch % ENC_CHECKPOINT_FREQ == 0:
            ...     enc.save_checkpoint(epoch, optimizer.state_dict(), loss)

        Parameters
        ----------
        epoch_int : int
            Current training epoch (zero-indexed or one-indexed — callers decide).
        optimizer_state_dict : dict | None
            Optimizer state to include for resumable training.  Pass ``None``
            if only the model weights are needed.
        loss_float : float | None
            Scalar training loss at this epoch for bookkeeping.

        Returns
        -------
        str
            Absolute path of the written checkpoint file.
        """
        registry_path: Path = Path(self._config_data.checkpoint_dir_str)
        registry_path.mkdir(parents=True, exist_ok=True)

        checkpoint_file_path: Path = (
            registry_path / f"tstcc_encoder_epoch_{epoch_int:04d}.pt"
        )

        payload_dict: Dict = {
            "epoch_int":            epoch_int,
            "state_dict":           self.state_dict(),
            "use_projection_bool":  self.use_projection_bool,
            "embed_dim_int":        self._config_data.embed_dim_int,
            "gru_hidden_int":       self._config_data.gru_hidden_int,
        }
        if optimizer_state_dict is not None:
            payload_dict["optimizer_state_dict"] = optimizer_state_dict
        if loss_float is not None:
            payload_dict["loss_float"] = loss_float

        torch.save(payload_dict, str(checkpoint_file_path))

        logger_obj.info(
            "[TstccEncoder] Checkpoint saved at epoch %d → %s",
            epoch_int,
            checkpoint_file_path,
        )

        return str(checkpoint_file_path.resolve())

    # ── Private helpers ───────────────────────────────────────────────────────

    def _run_gru(
        self,
        gru_input_tensor: torch.Tensor,
        lengths_tensor: Optional[torch.Tensor],
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Run the GRU with optional variable-length sequence packing.

        Using ``pack_padded_sequence`` / ``pad_packed_sequence`` ensures:
          * Padded positions do NOT update the GRU hidden state.
          * Gradient flow is only through actual sequence content.
          * Batch items can have different lengths without information leakage.

        Parameters
        ----------
        gru_input_tensor : Tensor
            Shape ``(batch, seq_len, gru_input_dim)``.
        lengths_tensor : Tensor | None
            Shape ``(batch,)``; actual (non-padded) lengths per batch item.

        Returns
        -------
        gru_output_tensor : Tensor
            Shape ``(batch, seq_len, gru_hidden_dim)``.
            Padded positions are zero-filled.
        valid_mask_tensor : Tensor | None
            Boolean mask shape ``(batch, seq_len)``; ``True`` = valid timestep.
            ``None`` when ``lengths_tensor`` is ``None`` (no masking needed).
        """
        if lengths_tensor is not None:
            # pack_padded_sequence requires CPU lengths and does not need sorted input
            packed_input = pack_padded_sequence(
                gru_input_tensor,
                lengths=lengths_tensor.cpu(),
                batch_first=True,
                enforce_sorted=False,   # handles unsorted batches (common in data loaders)
            )

            packed_output, _ = self.gru_module(packed_input)

            gru_output_tensor, _ = pad_packed_sequence(
                packed_output,
                batch_first=True,
                total_length=gru_input_tensor.size(1),  # pad back to original seq_len
            )
            # gru_output_tensor: (batch, seq_len, gru_hidden)
            # Padded positions are zero-filled by pad_packed_sequence.

            # Build attention mask: True where t < lengths[b]
            max_seq_len_int: int = gru_input_tensor.size(1)
            device_obj = gru_input_tensor.device
            time_range_tensor: torch.Tensor = torch.arange(
                max_seq_len_int, device=device_obj
            ).unsqueeze(0)                                  # (1, seq_len)
            valid_mask_tensor: torch.Tensor = (
                time_range_tensor < lengths_tensor.unsqueeze(1).to(device_obj)
            )                                               # (batch, seq_len)

        else:
            # All sequences have the same length — no packing needed.
            gru_output_tensor, _ = self.gru_module(gru_input_tensor)
            valid_mask_tensor = None

        return gru_output_tensor, valid_mask_tensor


# ─────────────────────────────────────────────────────────────────────────────
# Factory helper
# ─────────────────────────────────────────────────────────────────────────────

def build_tstcc_encoder(config: TstccEncoderConfigData) -> TstccEncoder:
    """
    Construct a fully wired :class:`TstccEncoder` from a config object.

    Serves as the single assembly point so downstream modules (P2-M3,
    P2-M4, P1-M4) do not need to know about internal layer wiring.

    Parameters
    ----------
    config : TstccEncoderConfigData
        Full encoder configuration.

    Returns
    -------
    TstccEncoder
        Ready-to-use encoder.  All sub-layers are constructed and wired.

    Example
    -------
    >>> from phase1.models.tstcc_encoder import (
    ...     build_tstcc_encoder,
    ...     TstccEncoderConfigData,
    ...     EmbeddingLayerConfigData,
    ...     CategoricalFieldConfigData,
    ... )
    >>> cfg = TstccEncoderConfigData(
    ...     embedding_cfg=EmbeddingLayerConfigData(
    ...         categorical_fields_list=[
    ...             CategoricalFieldConfigData("cloud_provider", 5,  8),
    ...             CategoricalFieldConfigData("region",         50, 16),
    ...             CategoricalFieldConfigData("service_type",   30, 16),
    ...             CategoricalFieldConfigData("operation_id",   200, 32),
    ...         ],
    ...         num_numeric_int=28,
    ...     )
    ... )
    >>> encoder = build_tstcc_encoder(cfg)
    """
    embedding_layer_obj: EmbeddingLayer = EmbeddingLayer(config.embedding_cfg)
    return TstccEncoder(config=config, embedding_layer=embedding_layer_obj)


# ─────────────────────────────────────────────────────────────────────────────
# Schema-tuned defaults for aug_pairs.parquet  (EVENT-BASED — revised)
# ─────────────────────────────────────────────────────────────────────────────
#
# Earlier versions of this module assumed every resource type emits the same
# six VM-style metrics (cpu_usage, memory_usage, ...). That assumption does
# not hold across a real multi-cloud fleet — an Azure Storage account emits
# Availability/Egress/Transactions/...; a VM emits cpu_usage/memory_usage/....
# There is no shared six-metric schema across resource types.
#
# Each row of aug_pairs.parquet is now treated as one reading EVENT:
# (timestamp, metric_name, value). 'metric_name' is a 4th categorical
# embedding column (the model learns what each metric means, rather than the
# pipeline hardcoding column names). 'value' is z-scored PER metric_name
# upstream (see streaming_aug_pairs_dataset.compute_metric_value_stats) into
# a derived 'value_norm' column before reaching the encoder. The legacy
# *_masked columns are no longer used as features — they were VM-shaped and
# didn't correspond to whatever metric a given row actually held.
#
# Encoder feature split for this schema:
#   numeric (3):       value_norm, hour_of_day, day_of_week
#                       (hour_of_day/day_of_week normalised to [0,1) upstream)
#   categorical (4):   cloud, entity_type, namespace, metric_name
#   timestamp (1):     timestamp → normalised fractional-hour fed into Time2Vec
#
# Practical consequence: a sequence window of length seq_len now spans
# seq_len consecutive READING EVENTS for an entity (interleaved across
# whatever metrics it emits), not seq_len distinct timestamps.
#
# Vocab sizes are DATA-DEPENDENT — they must be computed from your actual
# aug_pairs.parquet (not guessed), since metric_name/entity_type/namespace
# cardinality depends on what's in your Mongo collections. Compute them once
# locally via streaming_aug_pairs_dataset.compute_vocab_sizes(), then pass
# those counts into build_tstcc_encoder_for_aug_pairs() below.
# Vocab size = nunique + 1 (index 0 reserved for PAD/UNK) — handled internally.

AUG_PAIRS_TIME_SCALAR_COLS: List[str] = ["hour_of_day", "day_of_week"]

# Final ordered numeric feature list fed to EmbeddingLayer's nn.Linear path.
# THE ORDER OF THIS LIST IS THE CONTRACT: whatever tensor you pass as
# numeric_input_tensor must have its last dim laid out in exactly this order.
# 'value_norm' is a DERIVED column (z-scored per metric_name) — it does not
# exist as a raw column in the parquet file.
AUG_PAIRS_NUMERIC_COLS: List[str] = ["value_norm"] + AUG_PAIRS_TIME_SCALAR_COLS
AUG_PAIRS_NUM_NUMERIC: int = len(AUG_PAIRS_NUMERIC_COLS)  # = 3

# Categorical columns fed to EmbeddingLayer's nn.Embedding path, in order.
# metric_name is now included — see module-level note above.
AUG_PAIRS_CATEGORICAL_COLS: List[str] = ["cloud", "entity_type", "namespace", "metric_name"]

# precomputed time2vec_0..7 in the parquet are NOT used as encoder input —
# TstccEncoder computes its own learnable Time2Vec from the raw timestamp.
AUG_PAIRS_PRECOMPUTED_T2V_COLS: List[str] = [f"time2vec_{i}" for i in range(8)]


def build_tstcc_encoder_for_aug_pairs(
    cloud_vocab_size_int: int,
    entity_type_vocab_size_int: int,
    namespace_vocab_size_int: int,
    metric_name_vocab_size_int: int,
    use_projection_bool: bool = True,
    checkpoint_dir_str: str = ENC_MODEL_REGISTRY_DIR,
) -> TstccEncoder:
    """
    Construct a TstccEncoder pre-wired for the aug_pairs.parquet schema.

    Vocab sizes must be computed from YOUR local parquet file first
    (see module-level comment above for the one-liner). Pass the raw
    ``nunique()`` count — this function adds the PAD/UNK reservation
    internally, so do not add +1 yourself.

    Parameters
    ----------
    cloud_vocab_size_int : int
        Number of distinct values in the ``cloud`` column
        (``df['cloud'].nunique()``). Typically 4-5 (AWS/Azure/GCP/OCI/Unknown).
    entity_type_vocab_size_int : int
        Number of distinct values in ``entity_type``
        (``df['entity_type'].nunique()``).
    namespace_vocab_size_int : int
        Number of distinct values in ``namespace``
        (``df['namespace'].nunique()``).
    metric_name_vocab_size_int : int
        Number of distinct values in ``metric_name``
        (``df['metric_name'].nunique()``). This varies by resource type —
        compute it from your FULL file via
        ``streaming_aug_pairs_dataset.compute_vocab_sizes()``, not a single
        row-group sample, since different row groups may emit different
        resource types and therefore different metric sets.
    use_projection_bool : bool
        True for Phase-1 contrastive training (default). For inference-only
        construction, build with True, call load_weights(), then call
        disable_projection() — don't build with False and then load training
        checkpoints, since strict=True state_dict loading still expects the
        projection head's keys to exist in the checkpoint.
    checkpoint_dir_str : str
        Directory for periodic training checkpoints.

    Returns
    -------
    TstccEncoder
        Fully wired encoder: 3 numeric inputs, 4 categorical embedding
        columns (cloud, entity_type, namespace, metric_name), Time2Vec(k=8) →
        GRU(128, 2 layers) → AttentionPooling → ProjectionHead → L2-norm.

    Example
    -------
    >>> # 1. Compute vocab sizes from the FULL file (metric_name cardinality
    >>> #    can vary across row groups/resource types, so don't sample):
    >>> from phase1.data.streaming_aug_pairs_dataset import compute_vocab_sizes
    >>> vocab_maps = compute_vocab_sizes('aug_pairs.parquet')
    >>> cloud_n  = len(vocab_maps['cloud'])
    >>> etype_n  = len(vocab_maps['entity_type'])
    >>> ns_n     = len(vocab_maps['namespace'])
    >>> metric_n = len(vocab_maps['metric_name'])
    >>>
    >>> # 2. Build the encoder
    >>> encoder = build_tstcc_encoder_for_aug_pairs(cloud_n, etype_n, ns_n, metric_n)
    >>>
    >>> # 3. Forward pass — numeric/categorical tensors must follow
    >>> #    AUG_PAIRS_NUMERIC_COLS / AUG_PAIRS_CATEGORICAL_COLS column order
    >>> z = encoder(numeric_tensor, categorical_tensor, timestamps_tensor, lengths)
    """
    # Embed dim heuristic: min(vocab // 2, 32), floor of 4 to avoid degenerate
    # 0-1 dim embeddings on tiny vocabularies (e.g. cloud has only ~5 values).
    def _embed_dim(vocab_size_int: int) -> int:
        return max(4, min(vocab_size_int // 2, 32))

    cloud_full_vocab_int       = cloud_vocab_size_int + 1        # +1 reserves index 0 = PAD/UNK
    entity_type_full_vocab_int = entity_type_vocab_size_int + 1
    namespace_full_vocab_int   = namespace_vocab_size_int + 1
    metric_name_full_vocab_int = metric_name_vocab_size_int + 1

    cat_fields_list: List[CategoricalFieldConfigData] = [
        CategoricalFieldConfigData(
            field_name_str="cloud",
            vocab_size_int=cloud_full_vocab_int,
            embed_dim_int=_embed_dim(cloud_full_vocab_int),
            padding_idx_int=0,
        ),
        CategoricalFieldConfigData(
            field_name_str="entity_type",
            vocab_size_int=entity_type_full_vocab_int,
            embed_dim_int=_embed_dim(entity_type_full_vocab_int),
            padding_idx_int=0,
        ),
        CategoricalFieldConfigData(
            field_name_str="namespace",
            vocab_size_int=namespace_full_vocab_int,
            embed_dim_int=_embed_dim(namespace_full_vocab_int),
            padding_idx_int=0,
        ),
        CategoricalFieldConfigData(
            field_name_str="metric_name",
            vocab_size_int=metric_name_full_vocab_int,
            embed_dim_int=_embed_dim(metric_name_full_vocab_int),
            padding_idx_int=0,
        ),
    ]

    config = TstccEncoderConfigData(
        embedding_cfg=EmbeddingLayerConfigData(
            categorical_fields_list=cat_fields_list,
            num_numeric_int=AUG_PAIRS_NUM_NUMERIC,   # = 3
            output_dim_int=ENC_FEATURE_DIM,          # = 256
            numeric_proj_dim_int=ENC_FEATURE_DIM // 2,
        ),
        use_projection_bool=use_projection_bool,
        checkpoint_dir_str=checkpoint_dir_str,
    )

    logger_obj.info(
        "[build_tstcc_encoder_for_aug_pairs] cloud_vocab=%d  entity_type_vocab=%d  "
        "namespace_vocab=%d  metric_name_vocab=%d  numeric_features=%d",
        cloud_full_vocab_int, entity_type_full_vocab_int,
        namespace_full_vocab_int, metric_name_full_vocab_int, AUG_PAIRS_NUM_NUMERIC,
    )

    return build_tstcc_encoder(config)


# ─────────────────────────────────────────────────────────────────────────────
# Command-line entry point
# ─────────────────────────────────────────────────────────────────────────────
#
# Lets you run this file directly against your local aug_pairs.parquet to
# sanity-check that the encoder is correctly wired to your data before
# plugging it into the full P1-M4 NT-Xent training loop.
#
#   python tstcc_encoder.py --parquet /path/to/aug_pairs.parquet
#
# pandas/pyarrow/argparse are imported lazily here (not at module top) so
# importing TstccEncoder elsewhere doesn't require them as hard dependencies.

def _run_cli() -> None:
    import argparse
    import sys

    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq

    parser = argparse.ArgumentParser(
        description="Smoke-test TstccEncoder against a local aug_pairs.parquet file."
    )
    parser.add_argument("--parquet", required=True, help="Path to aug_pairs.parquet")
    parser.add_argument("--row-groups", type=int, default=1,
                         help="Number of row groups to sample (default: 1). "
                              "Each row group is typically ~1M rows; 1 is enough for a smoke test.")
    parser.add_argument("--seq-len", type=int, default=32,
                         help="Sequence window length per entity, IN READING EVENTS "
                              "not distinct timestamps (default: 32)")
    parser.add_argument("--max-entities", type=int, default=8,
                         help="Max number of entities to build sample sequences for (default: 8)")
    parser.add_argument("--save-checkpoint", action="store_true",
                         help="Save an (untrained) checkpoint to model_registry/ to verify save/load works")
    args = parser.parse_args()

    print("=" * 70)
    print("TstccEncoder — aug_pairs.parquet smoke test (event-based schema)")
    print("=" * 70)

    # ── Step 1: Load a sample of the parquet file (long format, no pivot) ──
    pq_file = pq.ParquetFile(args.parquet)
    total_rg_int = pq_file.num_row_groups
    rg_to_read_int = min(args.row_groups, total_rg_int)
    print(f"\n[1/5] Reading {rg_to_read_int}/{total_rg_int} row group(s) from {args.parquet} …")

    chunks = [pq_file.read_row_group(i).to_pandas() for i in range(rg_to_read_int)]
    df = pd.concat(chunks, ignore_index=True)
    print(f"      Loaded {len(df):,} rows × {len(df.columns)} columns")

    # Each row is already one (timestamp, metric_name, value) reading event —
    # no pivot needed. Just validate the raw columns this schema requires.
    required_raw_cols = {
        "entity_id", "timestamp", "view", "pair_id", "metric_name", "value",
        "cloud", "entity_type", "namespace", "hour_of_day", "day_of_week",
    }
    missing_cols = required_raw_cols - set(df.columns)
    if missing_cols:
        print(f"\n  ERROR: parquet is missing expected columns: {missing_cols}")
        print(f"  Found columns: {sorted(df.columns.tolist())}")
        sys.exit(1)

    # ── Step 2: Compute vocab + per-metric value stats, build the encoder ──
    print("\n[2/5] Computing categorical vocab sizes and per-metric value stats …")
    print("      NOTE: this smoke test computes stats from the SAMPLED row group(s) only.")
    print("      Real training (train_tstcc.py) computes these from the FULL file via")
    print("      compute_vocab_sizes()/compute_metric_value_stats() — metric_name and")
    print("      value-scale can both vary across row groups/resource types.")

    cloud_n  = int(df["cloud"].nunique())
    etype_n  = int(df["entity_type"].nunique())
    ns_n     = int(df["namespace"].nunique())
    metric_n = int(df["metric_name"].nunique())
    print(f"      cloud={cloud_n}  entity_type={etype_n}  namespace={ns_n}  metric_name={metric_n}")

    encoder = build_tstcc_encoder_for_aug_pairs(cloud_n, etype_n, ns_n, metric_n)
    encoder.eval()
    n_params_int = sum(p.numel() for p in encoder.parameters())
    print(f"      Encoder built. Total parameters: {n_params_int:,}")

    # ── Step 3: Build a handful of real (view_a, view_b) sequence pairs ───
    print(f"\n[3/5] Building sample sequence windows (seq_len={args.seq_len} reading events) …")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["value"] = df["value"].fillna(0.0).astype(np.float32)

    # Per-metric z-score stats, computed from this sample only (see NOTE above).
    metric_stats = df.groupby("metric_name")["value"].agg(["mean", "std"]).fillna(0.0)
    mean_map = metric_stats["mean"].to_dict()
    std_map = {k: (v if v > 1e-6 else 1.0) for k, v in metric_stats["std"].to_dict().items()}

    df["value_norm"] = (
        (df["value"] - df["metric_name"].map(mean_map)) / df["metric_name"].map(std_map)
    ).astype(np.float32)
    df["hour_of_day_norm"] = (df["hour_of_day"].fillna(0).astype(np.float32)) / 24.0
    df["day_of_week_norm"] = (df["day_of_week"].fillna(0).astype(np.float32)) / 7.0

    cloud_map  = {v: i + 1 for i, v in enumerate(sorted(df["cloud"].dropna().unique()))}
    etype_map  = {v: i + 1 for i, v in enumerate(sorted(df["entity_type"].dropna().unique()))}
    ns_map     = {v: i + 1 for i, v in enumerate(sorted(df["namespace"].dropna().unique()))}
    metric_map = {v: i + 1 for i, v in enumerate(sorted(df["metric_name"].dropna().unique()))}

    def encode_view(rows: pd.DataFrame):
        numeric = torch.tensor(
            rows[["value_norm", "hour_of_day_norm", "day_of_week_norm"]].to_numpy(dtype=np.float32)
        )
        cat = torch.tensor(
            [[cloud_map.get(r.cloud, 0), etype_map.get(r.entity_type, 0),
              ns_map.get(r.namespace, 0), metric_map.get(r.metric_name, 0)]
             for r in rows.itertuples()],
            dtype=torch.long,
        )
        frac_hour = (rows["timestamp"].dt.hour
                     + rows["timestamp"].dt.minute / 60.0
                     + rows["timestamp"].dt.second / 3600.0).to_numpy(dtype=np.float32) / 24.0
        ts = torch.tensor(frac_hour).unsqueeze(-1)
        return numeric, cat, ts

    entities = df["entity_id"].unique()[: args.max_entities]
    seq_a_list, seq_b_list = [], []
    used_entities = []

    for eid in entities:
        rows_a = df[(df["entity_id"] == eid) & (df["view"] == "a")].sort_values(["timestamp", "metric_name"])
        rows_b = df[(df["entity_id"] == eid) & (df["view"] == "b")].sort_values(["timestamp", "metric_name"])
        if len(rows_a) < args.seq_len or len(rows_b) < args.seq_len:
            continue
        seq_a_list.append(encode_view(rows_a.head(args.seq_len)))
        seq_b_list.append(encode_view(rows_b.head(args.seq_len)))
        used_entities.append(eid)

    if not seq_a_list:
        print(f"\n  ERROR: no entity had >= {args.seq_len} reading events for both view='a' and view='b'.")
        print(f"  Try a smaller --seq-len or a larger --row-groups.")
        sys.exit(1)

    print(f"      Built {len(seq_a_list)} matched pairs from entities: {used_entities}")

    numeric_a = torch.stack([s[0] for s in seq_a_list])
    cat_a     = torch.stack([s[1] for s in seq_a_list])
    ts_a      = torch.stack([s[2] for s in seq_a_list])
    numeric_b = torch.stack([s[0] for s in seq_b_list])
    cat_b     = torch.stack([s[1] for s in seq_b_list])
    ts_b      = torch.stack([s[2] for s in seq_b_list])

    # ── Step 4: Forward pass + sanity checks ───────────────────────────────
    print("\n[4/5] Running forward pass …")
    with torch.no_grad():
        z_a = encoder(numeric_a, cat_a, ts_a)
        z_b = encoder(numeric_b, cat_b, ts_b)

    print(f"      z_a shape: {tuple(z_a.shape)}   z_b shape: {tuple(z_b.shape)}")
    norms_a = z_a.norm(dim=-1)
    norms_b = z_b.norm(dim=-1)
    print(f"      L2 norms (should be 1.0): z_a min={norms_a.min():.6f} max={norms_a.max():.6f}")
    print(f"      L2 norms (should be 1.0): z_b min={norms_b.min():.6f} max={norms_b.max():.6f}")

    # Positive-pair similarity (matched a/b for same entity) vs.
    # negative-pair similarity (z_a[i] vs z_b[j], i != j) — sanity signal only;
    # the encoder is untrained at this point so these won't be well-separated yet.
    pos_sim = (z_a * z_b).sum(dim=-1)
    sim_matrix = z_a @ z_b.T
    neg_mask = ~torch.eye(len(z_a), dtype=torch.bool)
    neg_sim = sim_matrix[neg_mask]
    print(f"      Positive-pair cosine sim:  mean={pos_sim.mean():.4f}  (untrained encoder — not meaningful yet)")
    print(f"      Negative-pair cosine sim:  mean={neg_sim.mean():.4f}  (untrained encoder — not meaningful yet)")

    # ── Step 5: Optionally save a checkpoint to verify save/load works ────
    if args.save_checkpoint:
        print("\n[5/5] Saving checkpoint …")
        ckpt_path = encoder.save_checkpoint(epoch_int=0)
        print(f"      Saved to: {ckpt_path}")
    else:
        print("\n[5/5] Skipped checkpoint save (pass --save-checkpoint to enable)")

    print("\n" + "=" * 70)
    print("DONE. Encoder is correctly wired to this parquet's schema.")
    print("Next: plug encoder(...) calls into the P1-M4 NT-Xent training loop.")
    print("=" * 70)


if __name__ == "__main__":
    _run_cli()