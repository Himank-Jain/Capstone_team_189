"""
P1-M4  NTXentLossComputer — Normalized Temperature-scaled Cross-Entropy Loss
==============================================================================
CAPSTONE-189  |  Standard SimCLR-style contrastive loss for matched
(view_a, view_b) embedding pairs produced by TstccEncoder (P1-M3).

Given two batches of L2-normalised embeddings z_a, z_b (each shape (B, D)),
where z_a[i] and z_b[i] are augmented views of the SAME source record:

  1. Concatenate: z = [z_a ; z_b]                       shape (2B, D)
  2. Similarity:  S = (z @ z.T) / temperature            shape (2B, 2B)
  3. Mask the diagonal (self-similarity) to -inf so a sample is never
     compared against itself.
  4. For row i, the positive index is (i + B) mod 2B — i.e. z_a[i]'s
     positive is z_b[i], and z_b[i]'s positive is z_a[i].
  5. Loss = mean over all 2B rows of standard cross-entropy with the
     positive index as the target class.

This pulls matched pairs together and pushes all other 2(B-1) samples in
the batch apart, in both directions (a→b and b→a), which is the symmetric
NT-Xent formulation used in SimCLR.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

logger_obj: logging.Logger = logging.getLogger(__name__)


# Module-scoped constants (prefix: LOSS_)
LOSS_DEFAULT_TEMPERATURE: float = 0.1   # standard SimCLR default; lower = sharper contrast


@dataclass
class NTXentLossConfigData:
    """
    Configuration for :class:`NTXentLossComputer`.

    Parameters
    ----------
    temperature_float:
        Softmax temperature. Lower values sharpen the distribution (harder
        negatives matter more); typical range 0.05–0.5. SimCLR default: 0.1.
    """
    temperature_float: float = LOSS_DEFAULT_TEMPERATURE


class NTXentLossComputer(nn.Module):
    """
    Computes symmetric NT-Xent contrastive loss over matched embedding pairs.

    Parameters
    ----------
    config : NTXentLossConfigData
        Loss configuration (temperature). Injected via constructor (DIP).

    Example
    -------
    >>> loss_fn = NTXentLossComputer(NTXentLossConfigData(temperature_float=0.1))
    >>> z_a = encoder(numeric_a, cat_a, ts_a)   # (B, 128), L2-normalised
    >>> z_b = encoder(numeric_b, cat_b, ts_b)   # (B, 128), L2-normalised
    >>> loss = loss_fn(z_a, z_b)
    >>> loss.backward()
    """

    def __init__(self, config: NTXentLossConfigData | None = None) -> None:
        super().__init__()
        self._config_data: NTXentLossConfigData = config or NTXentLossConfigData()

        if self._config_data.temperature_float <= 0:
            raise ValueError(
                f"[NTXentLossComputer] temperature must be > 0, "
                f"got {self._config_data.temperature_float}"
            )

    def forward(self, z_a: torch.Tensor, z_b: torch.Tensor) -> torch.Tensor:
        """
        Compute the symmetric NT-Xent loss for a batch of matched pairs.

        Parameters
        ----------
        z_a : Tensor
            View-A embeddings, shape (B, D). Expected to already be
            L2-normalised (TstccEncoder guarantees this).
        z_b : Tensor
            View-B embeddings, shape (B, D), matched index-for-index with z_a.

        Returns
        -------
        Tensor
            Scalar loss value.

        Raises
        ------
        ValueError
            If z_a and z_b have mismatched shapes, or batch size < 2
            (need at least one negative to contrast against).
        """
        if z_a.shape != z_b.shape:
            raise ValueError(
                f"[NTXentLossComputer] Shape mismatch: z_a={tuple(z_a.shape)} "
                f"vs z_b={tuple(z_b.shape)}"
            )

        batch_size_int: int = z_a.size(0)
        if batch_size_int < 2:
            raise ValueError(
                f"[NTXentLossComputer] Need batch_size >= 2 for negatives, "
                f"got {batch_size_int}"
            )

        device_obj = z_a.device
        temperature_float: float = self._config_data.temperature_float

        # Step 1: concat views → (2B, D)
        z_all_tensor: torch.Tensor = torch.cat([z_a, z_b], dim=0)

        # Step 2: full similarity matrix → (2B, 2B), scaled by temperature
        sim_matrix_tensor: torch.Tensor = (
            z_all_tensor @ z_all_tensor.T
        ) / temperature_float

        # Step 3: mask self-similarity (diagonal) to -inf
        two_b_int: int = 2 * batch_size_int
        self_mask_tensor: torch.Tensor = torch.eye(
            two_b_int, dtype=torch.bool, device=device_obj
        )
        sim_matrix_tensor = sim_matrix_tensor.masked_fill(self_mask_tensor, float("-inf"))

        # Step 4: positive index for row i is (i + B) mod 2B
        positive_idx_tensor: torch.Tensor = (
            torch.arange(two_b_int, device=device_obj) + batch_size_int
        ) % two_b_int

        # Step 5: symmetric cross-entropy — each row's "correct class" is its
        # positive's column index in the similarity matrix.
        loss_tensor: torch.Tensor = F.cross_entropy(sim_matrix_tensor, positive_idx_tensor)

        return loss_tensor

    @property
    def temperature_float(self) -> float:
        return self._config_data.temperature_float
