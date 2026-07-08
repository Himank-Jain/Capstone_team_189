"""
phase0/seasonality/seasonality_classifier.py
=================================================
Phase 0 · SeasonalityClassifier — decides, per metric_name, whether a
bucketed (hourly/weekday-weekend) or a single global rolling baseline is
appropriate. Config-driven allowlist/denylist by default (simple,
deterministic) — a statistical variant (comparing within-bucket vs
across-bucket variance) is a documented future enhancement, not built
here, since it requires a batch of historical data to run against and
Phase 0's MVP should work correctly without it.
"""

from __future__ import annotations

from typing import Iterable, Optional, Set


class SeasonalityClassifier:
    """
    Parameters
    ----------
    non_seasonal_metrics:
        metric_names known to have no meaningful time-of-day pattern
        (e.g. a slowly-changing disk capacity counter). These always get
        the GLOBAL fallback baseline, regardless of vm_id.
    seasonal_metrics:
        Optional explicit allowlist of metric_names known to be seasonal.
        If provided, ANY metric not in this set is treated as
        non-seasonal (stricter denylist -> allowlist inversion). If left
        None, the default is "everything is seasonal except
        non_seasonal_metrics" (the more common case: most VM metrics
        like cpu/memory DO have daily patterns).
    """

    def __init__(
        self,
        non_seasonal_metrics: Optional[Iterable[str]] = None,
        seasonal_metrics: Optional[Iterable[str]] = None,
    ) -> None:
        self._non_seasonal: Set[str] = set(non_seasonal_metrics or [])
        self._seasonal_allowlist: Optional[Set[str]] = (
            set(seasonal_metrics) if seasonal_metrics is not None else None
        )

    def is_seasonal(self, vm_id: str, metric_name: str) -> bool:
        """vm_id is accepted for interface symmetry / future per-VM
        overrides, but the default implementation only keys on
        metric_name — daily patterns are almost always a property of the
        metric type, not the specific machine."""
        if metric_name in self._non_seasonal:
            return False
        if self._seasonal_allowlist is not None:
            return metric_name in self._seasonal_allowlist
        return True
