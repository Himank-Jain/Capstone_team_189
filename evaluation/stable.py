"""
Strategy-independent ground-truth label for a real series.

An entity is STABLE if, after the event day, no 14-day window of its own data sits more than
`thresh` hour-scale units from its level in the reference days (weekday and weekend compared separately).
This uses only the raw series and the same unit as the injected attacks, never any detector's output,
so false alerts on STABLE entities are false by construction and shifted entities are a separate class.
"""
from __future__ import annotations
import numpy as np


def max_shift(values: np.ndarray, hour_scale: float, ref_days: int, start_day: int, start_weekday: int = 0) -> float:
    d = np.median(values.reshape(-1, 24), axis=1)
    n = len(d)
    wk = (np.arange(n) + start_weekday) % 7 >= 5
    worst = 0.0
    for grp in (False, True):
        ref = d[:ref_days][wk[:ref_days] == grp]
        if len(ref) < 3:
            continue
        m0 = np.median(ref)
        idx = np.where(wk == grp)[0]
        idx = idx[idx >= start_day]
        for i in range(len(idx)):
            w = idx[(idx >= idx[i]) & (idx < idx[i] + 14)]
            if len(w) < 3:
                continue
            worst = max(worst, abs(np.median(d[w]) - m0) / hour_scale)
    return worst
