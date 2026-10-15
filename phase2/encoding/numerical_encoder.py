"""
phase2/encoding/numerical_encoder.py
========================================
P2-M2  |  NumericalEncoder — per-metric_name z-score of the single `value`
reading. Deliberately NOT a generic LayerNorm — see the Phase 1 Architecture
Addendum: different metrics live on wildly different raw scales (e.g.
'Availability' in [0,100] vs 'Available Memory Bytes' in the billions), so
a single global scaler or LayerNorm would let whichever metric has the
largest raw magnitude dominate.

Must match streaming_aug_pairs_dataset.py's _process_row_group() EXACTLY:

    value = value.fillna(0.0)
    row_mean = metric_name.map(mean_map).fillna(0.0)
    row_std  = metric_name.map(std_map).fillna(1.0)
    value_norm = (value - row_mean) / (row_std + AUG_VALUE_NORM_EPS)

Falling back to mean=0.0/std=1.0 for an unseen metric_name means an OOV
metric's value_norm equals its raw value (unscaled) — not ideal, but
matches training-time behavior exactly rather than inventing a different
fallback that would diverge from the trained model's assumptions.
"""

from __future__ import annotations

import logging
from typing import Dict, Tuple

from shared.constants import AUG_VALUE_NORM_EPS

logger_obj = logging.getLogger(__name__)


class NumericalEncoder:
    """
    Parameters
    ----------
    metric_value_stats_dict:
        {metric_name: (mean, std)} — sourced from FeatureMetaStore, which
        in turn must come from the SAME compute_metric_value_stats()
        output used to train the loaded TstccEncoder checkpoint.
    online_oov_stats:
        If True, a metric the checkpoint has never seen is standardised with
        statistics learned online from its own readings (Welford), instead of
        passing through unscaled. Until ``online_min_count`` readings have been
        seen it encodes as 0.0 (the neutral value), so a brand-new metric cannot
        inject a huge raw magnitude into the encoder. In-vocabulary metrics are
        untouched, so behaviour on the trained schema is identical. Default
        False keeps the original training-time fallback.
    """

    def __init__(
        self,
        metric_value_stats_dict: Dict[str, Tuple[float, float]],
        online_oov_stats: bool = False,
        online_min_count: int = 8,
    ) -> None:
        self._stats_dict = metric_value_stats_dict
        self._oov_metric_count = 0
        self._online = online_oov_stats
        self._online_min = online_min_count
        self._online_state: Dict[str, Tuple[int, float, float]] = {}  # count, mean, m2

    def encode(self, metric_name: str, raw_value: float) -> float:
        """Z-score `raw_value` using metric_name's precomputed (mean, std)."""
        value = (
            0.0 if raw_value is None or raw_value != raw_value else float(raw_value)
        )  # NaN check
        if metric_name not in self._stats_dict:
            self._oov_metric_count += 1
            if self._online:
                return self._encode_online(metric_name, value)
            logger_obj.debug(
                "[NumericalEncoder] No stats for metric_name=%r — using "
                "mean=0.0/std=1.0 fallback (value passes through unscaled)",
                metric_name,
            )
        mean, std = self._stats_dict.get(metric_name, (0.0, 1.0))
        return (value - mean) / (std + AUG_VALUE_NORM_EPS)

    def _encode_online(self, metric_name: str, value: float) -> float:
        count, mean, m2 = self._online_state.get(metric_name, (0, 0.0, 0.0))
        if count >= self._online_min:
            std = (m2 / count) ** 0.5
            out = (value - mean) / (std + AUG_VALUE_NORM_EPS)
        else:
            out = 0.0
        count += 1
        delta = value - mean
        mean += delta / count
        m2 += delta * (value - mean)
        self._online_state[metric_name] = (count, mean, m2)
        return out

    @property
    def oov_metric_count(self) -> int:
        return self._oov_metric_count
