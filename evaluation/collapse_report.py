"""Summary of collapse_<ds>.json: flagged days per run, incidents per run, share of flagged days that attach to an open incident.

    python -m evaluation.collapse_report <cs_dev|cs_fresh2>
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"


def main(ds: str):
    rows = json.loads((OUT / f"collapse_{ds}.json").read_text())["rows"]
    out = {}
    for s in ("control", "stealth2.0", "stealth3.0", "fast4", "benign", "greedy"):
        runs = [r["runs"][s] for r in rows if s in r["runs"]]
        flagged = [r for r in runs if r["flag_days"]]
        if not flagged:
            out[s] = {"runs": len(runs), "runs_with_flags": 0}
            continue
        fd = np.array([len(r["flag_days"]) for r in flagged])
        inc = np.array([len(r["incidents"]) for r in flagged])
        col = np.array([len(r["collapsed"]) for r in flagged])
        out[s] = {"runs": len(runs), "runs_with_flags": len(flagged), "median_flag_days": float(np.median(fd)),
                  "median_incidents": float(np.median(inc)), "share_flag_days_collapsed": float(col.sum() / fd.sum()),
                  "median_held_days": float(np.median([r["held_days"] for r in flagged]))}
        print(ds, s, json.dumps(out[s]))
    (OUT / f"collapse_summary_{ds}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
