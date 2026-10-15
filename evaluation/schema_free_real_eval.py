"""
Invention C on real telemetry: does the event-level encoder keep detecting an injected shift when the entity's schema
(cloud / entity type / namespace / metric name) is one the checkpoint has never seen?

    python -m evaluation.schema_free_real_eval <cs_dev|cs_fresh2>

Checkpoint: registry version 0.1.0 (126 metric names, 20 entity types), trained on the team's own corpus. It may have seen some of
these CoreStack series or their types during training, so the in-vocabulary condition is NOT held-out data; the evidence for
claim C is the contrast with the same readings under unseen names, and the series whose metric or type is genuinely absent from
the vocabulary (fresh2 only).

Per entity (hourly, one metric): baseline = windows from days 0-29 (centroid of embeddings); negatives = windows from days 30 to the
event day; positives = windows after the injected 3σ shift (10-day ramp) is complete. Score = cosine distance to the centroid;
AUC per entity. Comparator without learning: |median(window) - median(baseline)| / robust scale of the baseline hours.

Conditions
  in_vocab        names as recorded; only entities whose metric and type are both in the vocabulary
  renamed_pass    same readings, names unseen, raw value passes through (the original fallback)
  renamed_online  same readings, names unseen, per-metric statistics learned online from days 0-29
  natural_oov_*   entities whose metric or type is genuinely unseen (as recorded), passthrough / online
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

DATASET = sys.argv[1]
os.environ["EVAL_PROFILE"] = {"cs_dev": "corestack", "cs_fresh2": "corestack90"}[DATASET]
_argv = sys.argv
sys.argv = ["x", DATASET, "none"]
import numpy as np  # noqa: E402
import torch  # noqa: E402

import evaluation.final_eval as fe  # noqa: E402
from evaluation.data import SIM_START  # noqa: E402
from evaluation.scenarios import EVENT_DAY, END_DAY, Scenario, apply_scenario  # noqa: E402
from evaluation.schema_free_eval import _auc  # noqa: E402
from phase2.encoding.record_encoder import RecordEncoder  # noqa: E402
from phase2.encoding.reference_encoder_service import load_inference_encoder_from_manifest  # noqa: E402
from shared.types import RawRecord  # noqa: E402

sys.argv = _argv
OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"
SEQ = 32
SHIFT = float(os.environ.get("SF_SHIFT", "3.0"))
NS = {
    "Storage_Accounts": "Microsoft.Storage/storageAccounts", "Disks": "Microsoft.Compute/disks",
    "Virtual_Machines": "Microsoft.Compute/virtualMachines", "Appservice_Plan": "Microsoft.Web/serverfarms",
    "Event_Hub_Namespaces": "Microsoft.EventHub/namespaces", "Container_Groups": "Microsoft.ContainerInstance/containerGroups",
    "Vaults": "Microsoft.KeyVault/vaults", "Recovery_Service_Vaults": "Microsoft.RecoveryServices/vaults",
    "Public_IP_Address": "Microsoft.Network/publicIPAddresses", "MS-SQL_DB": "Microsoft.Sql/servers/databases",
    "Private_DNS_Zones": "Microsoft.Network/privateDnsZones",
}


def _records(values: np.ndarray, cloud, etype, ns, metric, lo_day, hi_day):
    return [RawRecord(entity_id="e", timestamp=SIM_START + timedelta(days=d, hours=h), cloud=cloud, entity_type=etype,
                      namespace=ns, metric_name=metric, value=float(values[d * 24 + h]))
            for d in range(lo_day, hi_day) for h in range(24)]


def _windows(recs, stride):
    return [recs[i:i + SEQ] for i in range(0, len(recs) - SEQ + 1, stride)]


def _embed(enc, rec_enc, windows):
    encoded = [rec_enc.encode_entity_records(w) for w in windows]
    ids, num, cat, ts, ln = RecordEncoder.collate_encoded_batch({str(i): e for i, e in enumerate(encoded)})
    with torch.no_grad():
        return enc.encode(num, cat, ts, ln).cpu().numpy()


def _auc_entity(enc, meta, values, schema, online: bool):
    cloud, etype, ns, metric = schema
    rec_enc = RecordEncoder(meta, seq_len=SEQ, online_oov_stats=online)
    base = _records(values, cloud, etype, ns, metric, 0, 30)
    if online:
        rec_enc.observe_records(base)
    cen = _embed(enc, rec_enc, _windows(base, 16)).mean(0)
    cen /= np.linalg.norm(cen) + 1e-12
    neg = _windows(_records(values, cloud, etype, ns, metric, 30, EVENT_DAY), 8)
    pos = _windows(_records(values, cloud, etype, ns, metric, EVENT_DAY + 10, END_DAY), 8)
    if len(neg) < 5 or len(pos) < 5:
        return None
    score = lambda ws: 1.0 - _embed(enc, rec_enc, ws) @ cen
    return _auc(score(neg), score(pos))


def _auc_zscore(values):
    h = values[: 30 * 24]
    med = np.median(h)
    sc = 1.4826 * np.median(np.abs(h - med)) + 1e-9
    def win(lo, hi):
        v = values[lo * 24: hi * 24]
        return [abs(np.median(v[i:i + SEQ]) - med) / sc for i in range(0, len(v) - SEQ + 1, 8)]
    neg, pos = win(30, EVENT_DAY), win(EVENT_DAY + 10, END_DAY)
    if len(neg) < 5 or len(pos) < 5:
        return None
    return _auc(np.array(neg), np.array(pos))


def main():
    torch.manual_seed(0)
    enc, meta = load_inference_encoder_from_manifest("model_registry/artifacts_manifest.json", "0.1.0")
    vm = meta.vocab_maps_dict
    ents = fe.build()
    rows = []
    for i, e in enumerate(ents):
        cat, metric = e.group.split(":", 1)
        sc = Scenario("attack", "linear", SHIFT, ramp_days=10, seed=i)
        values = apply_scenario(e, sc)
        cloud = "GCP" if "googleapis" in metric else "Azure"
        ns = NS.get(cat, "")
        in_v = metric in vm["metric_name"] and cat in vm["entity_type"]
        row = {"entity": e.entity_id, "resource": e.source, "cat": cat, "metric": metric, "in_vocab": in_v,
               "zscore": _auc_zscore(values)}
        if in_v:
            row["in_vocab_auc"] = _auc_entity(enc, meta, values, (cloud, cat, ns, metric), False)
            unseen = ("GCP", "Type_unseen", "unseen/ns", f"M_unseen_{i}")
            row["renamed_pass"] = _auc_entity(enc, meta, values, unseen, False)
            row["renamed_online"] = _auc_entity(enc, meta, values, unseen, True)
        else:
            row["natural_pass"] = _auc_entity(enc, meta, values, (cloud, cat, ns, metric), False)
            row["natural_online"] = _auc_entity(enc, meta, values, (cloud, cat, ns, metric), True)
        rows.append(row)
        if (i + 1) % 25 == 0:
            print(DATASET, i + 1, "of", len(ents), flush=True)
    (OUT / f"schema_free_real_{DATASET}{'' if SHIFT == 3.0 else '_shift' + str(SHIFT)}.json").write_text(json.dumps({"dataset": DATASET, "rows": rows}))


if __name__ == "__main__":
    main()
