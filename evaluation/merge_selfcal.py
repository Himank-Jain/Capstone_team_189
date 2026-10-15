"""Merge the tuned-design rows (final_eval) with the self-calibrated rows (selfcal_eval) so final_report can compare them.
   python -m evaluation.merge_selfcal <dataset>   ->  final_<dataset>_0.05B.json  (report with: python -m evaluation.final_report <dataset> 0.05B)"""
import json, sys
from pathlib import Path
OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"
ds = sys.argv[1]
A = json.load(open(OUT / f"final_{ds}_0.05.json"))
B = json.load(open(OUT / f"selfcal_{ds}_0.05.json"))
assert len(A["rows"]) == len(B["rows"])
for a, b in zip(A["rows"], B["rows"]):
    assert a["id"] == b["id"] and a["source"] == b["source"]
    a["res"].update(b["res"])
    a["self_cal"] = b["self_cal"]
(OUT / f"final_{ds}_0.05B.json").write_text(json.dumps({"thresholds": {"tuned": A["thresholds"], "self_calibrated": {"alpha": B["alpha"], "B": B["B"]}}, "rows": A["rows"]}))
print("merged", len(A["rows"]))
