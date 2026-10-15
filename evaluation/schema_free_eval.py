"""
Invention C evaluation: does the schema-free encoder keep detecting
behavioural deviations when an entity uses cloud / namespace / metric
names the checkpoint was never trained on?

Score = cosine distance between a window embedding and the entity's
centroid of baseline-window embeddings. AUC = how well that score ranks
anomalous windows above normal ones, per entity, averaged over entities.

Conditions
  in_vocab        metrics, namespace and cloud the checkpoint was trained on
  oov_passthrough unseen schema, original fallback (mean 0, std 1: raw value passes through)
  oov_online      unseen schema, statistics learned online (this work)

The telemetry is synthetic (seasonal + noise, seeded); the checkpoint is the
repo's own synthetic_32 bundle. This measures robustness to schema change on
that checkpoint, not accuracy on production data.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np
import torch

from phase2.encoding.record_encoder import RecordEncoder
from phase2.encoding.reference_encoder_service import load_inference_encoder_from_manifest
from shared.types import RawRecord

START = datetime(2026, 1, 5)
STEP_MIN = 5
BASE_DAYS, TEST_DAYS = 2, 1
SEQ = 32

SCHEMAS = {
    "in_vocab": dict(cloud="AWS", entity_type="Instances", namespace="AWS/EC2",
                     metrics=[("CPUUtilization", 25.0, 19.8), ("NetworkIn", 66318.0, 50254.0)]),
    "oov": dict(cloud="GCP", entity_type="GceInstance", namespace="compute.googleapis.com",
                metrics=[("queue_depth", 50000.0, 10000.0), ("gc_pause_ms", 300.0, 60.0)]),
}


def _series(rng, spec, entity, anomalous_from=None, kind="shift"):
    recs: List[RawRecord] = []
    n = (BASE_DAYS + TEST_DAYS) * 24 * 60 // STEP_MIN
    level = {m: mu * rng.uniform(0.7, 1.3) for m, mu, _ in spec["metrics"]}
    for i in range(n):
        t = START + timedelta(minutes=i * STEP_MIN)
        season = math.sin(2 * math.pi * (t.hour + t.minute / 60) / 24)
        for m, mu, sd in spec["metrics"]:
            v = level[m] + 0.5 * sd * season + rng.gauss(0, 0.35 * sd)
            if anomalous_from is not None and i >= anomalous_from:
                v += 4.0 * sd if kind == "shift" else (6.0 * sd if rng.random() < 0.25 else 0.0)
            recs.append(RawRecord(entity_id=entity, timestamp=t, cloud=spec["cloud"],
                                  entity_type=spec["entity_type"], namespace=spec["namespace"],
                                  metric_name=m, value=v))
    return recs


def _windows(recs: List[RawRecord], lo: int, hi: int, stride: int) -> List[List[RawRecord]]:
    per_step = len({r.metric_name for r in recs})
    seg = recs[lo * per_step: hi * per_step]
    w = SEQ
    return [seg[i:i + w] for i in range(0, len(seg) - w + 1, stride)]


def _auc(neg: np.ndarray, pos: np.ndarray) -> float:
    allv = np.concatenate([neg, pos])
    ranks = allv.argsort().argsort() + 1.0
    # average ranks for ties
    _, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=ranks)
    ranks = (sums / cnt)[inv]
    r_pos = ranks[len(neg):].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def _embed(enc, rec_enc, windows):
    encoded = [rec_enc.encode_entity_records(w) for w in windows]
    ids, num, cat, ts, ln = RecordEncoder.collate_encoded_batch({str(i): e for i, e in enumerate(encoded)})
    return enc.encode(num, cat, ts, ln).cpu().numpy()


def run(n_entities: int = 30, seed: int = 7, kinds=("shift", "spike")) -> Dict:
    inf, meta = load_inference_encoder_from_manifest("model_registry/artifacts_manifest.json", "0.2.0")
    steps_base = BASE_DAYS * 288
    steps_all = (BASE_DAYS + TEST_DAYS) * 288
    anom_from = steps_base + 144  # second half of day 3 is anomalous
    out: Dict = {"n_entities": n_entities, "seed": seed, "seq_len": SEQ, "conditions": {}}
    plan = [("in_vocab", "in_vocab", False), ("oov_passthrough", "oov", False), ("oov_online", "oov", True)]
    for kind in kinds:
        for cname, sname, online in plan:
            aucs: List[float] = []
            for e in range(n_entities):
                rng = random.Random(seed * 1000 + e)
                normal = _series(rng, SCHEMAS[sname], f"e{e}")
                rng2 = random.Random(seed * 1000 + e)
                anom = _series(rng2, SCHEMAS[sname], f"e{e}", anom_from, kind)
                rec_enc = RecordEncoder(meta, seq_len=SEQ, online_oov_stats=online)
                if online:
                    rec_enc.observe_records(normal[: steps_base * len(SCHEMAS[sname]["metrics"])])
                base_w = _windows(normal, 0, steps_base, 16)
                cen = _embed(inf, rec_enc, base_w).mean(0)
                cen /= np.linalg.norm(cen) + 1e-12
                neg_w = _windows(anom, steps_base, anom_from, 8)
                pos_w = _windows(anom, anom_from + SEQ // len(SCHEMAS[sname]["metrics"]), steps_all, 8)
                score = lambda ws: 1.0 - _embed(inf, rec_enc, ws) @ cen
                aucs.append(_auc(score(neg_w), score(pos_w)))
            a = np.array(aucs)
            boot = np.random.default_rng(0).choice(a, (2000, len(a))).mean(1)
            out["conditions"][f"{kind}/{cname}"] = {
                "auc_mean": float(a.mean()), "auc_median": float(np.median(a)),
                "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                "frac_entities_auc_ge_0.9": float((a >= 0.9).mean()),
            }
    return out


if __name__ == "__main__":
    import json
    torch.manual_seed(0)
    r = run()
    json.dump(r, open("docs/patent_evaluation/schema_free_results.json", "w"), indent=2)
    for k, v in r["conditions"].items():
        print(f"{k:28s} AUC {v['auc_mean']:.3f}  CI {v['ci95'][0]:.3f}-{v['ci95'][1]:.3f}  >=0.9: {v['frac_entities_auc_ge_0.9']:.2f}")
