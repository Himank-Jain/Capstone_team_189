"""Condense docs/patent_evaluation/*.json into the summary the dashboard renders."""
import json, pathlib, sys

root = pathlib.Path("docs/patent_evaluation")
src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else root
sf = json.load(open(root / "schema_free_results.json"))
ex = json.load(open(root / "explanation_results.json"))
man = json.load(open("model_registry/artifacts_manifest.json"))

SHOW = ["adaptive", "frozen", "rollback", "cusum_r", "guard_cal", "dual_noledger", "dual"]
LABELS = {"adaptive": "Adaptive baseline", "frozen": "Frozen baseline", "rollback": "Rollback", "cusum_r": "Clipped CUSUM",
          "guard_cal": "Calibrated bound guard", "dual_noledger": "Dual trigger, no ledger", "dual": "Dual trigger + ledger (proposed)"}
DATASETS = [("nab_dev", "NAB development", "AWS CloudWatch, day-resampled (synthetic order); thresholds tuned here"),
            ("cs_dev", "CoreStack development", "real Azure telemetry; thresholds tuned here"),
            ("nab_fresh", "NAB fresh", "22 series from other NAB categories, run once after the design was frozen"),
            ("cs_fresh", "CoreStack fresh", "22 resources never run before; only 8 clean entities")]
fz = json.load(open(root / "final_summary.json"))


def pct(x):
    return None if x is None else {"rate": round(x["rate"], 4), "lo": round(x["lo"], 4), "hi": round(x["hi"], 4)}


frozen = []
for key, title, note in DATASETS:
    d = fz[key]
    rows = []
    for k in SHOW:
        st = d["strategies"][k]
        rows.append({"key": k, "label": LABELS[k], "fpr": pct(st["fpr"]), "tpr2": pct(st["tpr_stealth2.0"]), "tpr3": pct(st["tpr_stealth3.0"]),
                     "local": pct(st["tpr_local4"]), "poisoned": pct(st["tpr_poisoned"]),
                     "disp2": round(st["disp_stealth2.0"]["median"], 2),
                     "benign_unresolved": pct(st["benign_unresolved_of_flagged"]),
                     "real_unresolved": pct(st.get("real_shift_unresolved_of_flagged")),
                     "absorb": {o: (fz["absorption"][key].get(k) or {}).get(o, {}).get("attack_share_median") for o in ("14", "30", "60")},
                     "resolved": {o: (fz["absorption"][key].get(k) or {}).get(o, {}).get("benign_resolved") for o in ("14", "30", "60")}})
    frozen.append({"key": key, "title": title, "note": note, "entities": d["n_entities"], "series": d["n_sources"],
                   "clean_entities": d["n_clean_entities"], "clean_series": d["n_clean_sources"],
                   "shifted_series": d["n_shifted_sources"], "rows": rows})
versions = []
for v, e in man["versions"].items():
    fm = e["feature_meta_dict"]["vocab_maps"]
    versions.append({"version": v, "embedding_dim": e["config_dict"]["embedding_dim"],
                     "sequence_length": e["config_dict"]["sequence_length"],
                     "vocab": {k: len(x) for k, x in fm.items()}})
out = {
    "frozen": frozen,
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
print("ok", len(frozen), "datasets")
