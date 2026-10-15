#!/usr/bin/env python
"""Run the drift-guard evaluation on real public AWS CloudWatch telemetry.

Usage:  python scripts/run_patent_evaluation.py [--replicas 12] [--limit N]
Writes: docs/patent_evaluation/results_raw.json and results.json
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.runner import aggregate, run_grid  # noqa: E402

DATA = ROOT / "data" / "external" / "nab_aws_cloudwatch"


def ensure_data() -> None:
    if DATA.exists():
        return
    tmp = ROOT / "data" / "external" / "_nab_clone"
    subprocess.check_call(["git", "clone", "--depth", "1", "https://github.com/numenta/NAB", str(tmp)])
    DATA.parent.mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "realAWSCloudwatch").rename(DATA)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replicas", type=int, default=12)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", default=str(ROOT / "docs" / "patent_evaluation"))
    args = ap.parse_args()
    ensure_data()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw = run_grid(args.replicas, DATA, args.workers, args.limit)
    (out / "results_raw.json").write_text(json.dumps(raw))
    agg = aggregate(raw)
    agg["n_entities"] = raw["n_entities"]
    agg["sources"] = raw["sources"]
    agg["excluded_sources"] = raw["excluded_sources"]
    agg["cohort_stats"] = raw["tuned"]["cohort_stats"]
    agg["elapsed_s"] = raw["elapsed_s"]
    (out / "results.json").write_text(json.dumps(agg, indent=2))
    print(json.dumps({k: agg[k] for k in ("n_entities", "elapsed_s")}))


if __name__ == "__main__":
    main()
