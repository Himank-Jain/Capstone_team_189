"""Condense docs/patent_evaluation/*.json into the summary the dashboard renders."""
import json, pathlib, sys

root = pathlib.Path("docs/patent_evaluation")
src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else root
res = json.load(open(src / "results.json"))
sf = json.load(open(root / "schema_free_results.json"))
ex = json.load(open(root / "explanation_results.json"))
man = json.load(open("model_registry/artifacts_manifest.json"))

LABELS = {
    "adaptive": "Adaptive baseline (Phase 0)", "frozen": "Frozen baseline", "longwin": "Long window",
    "clip": "Update clipping", "cusum": "CUSUM", "rollback": "Rollback",
    "guard_default": "Drift guard, default 1.0σ / 2.0σ", "guard_cal": "Drift guard, calibrated per entity",
}
strategies = []
for k, label in LABELS.items():
    s = res["strategies"].get(k)
    if not s:
        continue
    strategies.append({
        "key": k, "label": label,
        "stored_drift": s["attack"]["median_stored_drift_at_ramp_end"],
        "attack": {"k": s["attack"]["k"], "n": s["attack"]["n"]},
        "control_alert": {"k": s["control_alert"]["k"], "n": s["control_alert"]["n"]},
        "benign_alert": {"k": s["benign"]["k"], "n": s["benign"]["n"]},
    })
versions = []
for v, e in man["versions"].items():
    fm = e["feature_meta_dict"]["vocab_maps"]
    versions.append({"version": v, "embedding_dim": e["config_dict"]["embedding_dim"],
                     "sequence_length": e["config_dict"]["sequence_length"],
                     "vocab": {k: len(x) for k, x in fm.items()}})
out = {
    "guard": {"n_entities": res["n_entities"], "strategies": strategies,
              "calibration": res.get("calibration_validation"), "promotion": res.get("promotion"),
              "calibrated_bounds": res.get("calibrated_bounds")},
    "schema_free": [{"key": k, "auc": v["auc_mean"], "ci95": v["ci95"]} for k, v in sf["conditions"].items()],
    "explanation": {"runs": ex["runs_total"], "identical_pct": ex["identical_pct"],
                    "median_ms": ex["latency_ms_median"], "p95_ms": ex["latency_ms_p95"],
                    "network_attempts": ex["network_connection_attempts"]},
    "models": versions,
}
cs = json.load(open(root / "cold_start_results.json"))
out["cold_start"] = {k: {"scoring_start_h": cs[k]["scoring_start_h"]["median"], "detected_k": cs[k]["detected_k"],
                         "n": cs["n_entities"], "delay_h": cs[k]["detect_delay_h"]["median"],
                         "false_per_100": cs[k]["false_alerts_per_100"]["median"]} for k in ("unseeded", "seeded")}
json.dump(out, open("frontend/src/data/evaluation.json", "w"), indent=1)
print("ok", len(strategies), "strategies")
