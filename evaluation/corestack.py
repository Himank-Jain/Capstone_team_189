"""
CoreStack data layer (derived from the three CoreStack-provided BSON dumps).

Derived files (built on the owner's machine, see docs/patent_evaluation/CORESTACK.md):
  corestack_series_90d.pkl     hourly metric series, 90 contiguous days, Monday-aligned
  corestack_events_daily.pkl   control-plane activity-log events per resource/day/operation
"""
from __future__ import annotations

import datetime as dt
import pickle
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

import numpy as np

DATA = Path("data/external/corestack")

# Operations that change a resource (configuration, lifecycle, scale, patching).
CHANGE_RE = re.compile(
    r"(/write$|/delete$|/start/action$|/stop/action$|/restart/action$|/deallocate/action$|"
    r"/installPatches/action$|/runCommand/action$|/upgradeVMAgent/action$|/scale/action$|"
    r"^CreateWebSite$|^StopWebSite$|^StartWebSite$|^DeleteWebSite$)", re.I)
# Excluded even though they match: alert-rule, policy, lock, tag and restore-point bookkeeping.
NOISE_RE = re.compile(r"(insights/|authorization/|advisor/|restorepoint|resources/tags|resources/deployments|locks/|resourcehealth)", re.I)
# Read-type operations used as a negative control.
READ_RE = re.compile(r"(listKeys|listClusterUserCredential|listClusterAdminCredential|listAccountSas)", re.I)


def load_series(name: str = "corestack_series_90d.pkl") -> Dict[tuple, dict]:
    return pickle.load(open(DATA / name, "rb"))


def load_events() -> Dict[str, Dict[str, Set[dt.date]]]:
    """resource(lowercase) -> {"change": {dates}, "read": {dates}, "any": {dates}}"""
    out: Dict[str, Dict[str, Set[dt.date]]] = defaultdict(lambda: {"change": set(), "read": set(), "any": set()})
    for rid, day, op, cat, st, n in pickle.load(open(DATA / "corestack_events_daily.pkl", "rb")):
        d = dt.date.fromisoformat(day)
        out[rid]["any"].add(d)
        if READ_RE.search(op):
            out[rid]["read"].add(d)
        elif CHANGE_RE.search(op) and not NOISE_RE.search(op) and st in ("Succeeded", "Started", "Accepted", "Updated", "Active", "Activated"):
            out[rid]["change"].add(d)
    return out


def daily_medians(values: np.ndarray) -> np.ndarray:
    return np.median(values.reshape(-1, 24), axis=1)
