"""
Corpus Generator for Contrastive SSL Pretraining (v2 — EDA-corrected)
=======================================================================
Capstone: Unified AIOps Framework — Intelligent Alerting System

Changes from v1, based on EDA findings (Step4a/4b outputs):
  1. detect_cloud(): now uses category/uri/resource/namespace fallback
     chain matching the logic that correctly classified the risk-scoring
     inventory (AWS 966K / OCI 32K / Azure 23K / GCP 160K). Metric docs
     often lack `namespace`, so category+uri carry most of the signal.
  2. Alert anchor query: strips tzinfo before querying Mongo, since
     event_creation_time is stored as naive datetimes. Also widens the
     anchor period to Nov 2025 (EDA Part E confirms data is concentrated
     there) and notes the entity-id namespace mismatch (OCID vs i-xxxx/
     Azure resourceId) — anchors will mostly match OCI entities; this is
     expected, not a bug, and is logged explicitly.
  3. Date range default moved to November 2025 (EDA Part E used Nov 2025
     and found real volume there; August had very few matching docs).
     $sample multiplier raised from 5x to 20x, and max_resources raised
     to get a workable pretraining corpus.

Usage:
  pip install pymongo pandas numpy scipy pyarrow tqdm
  python generate_corpus.py
"""

import os
import json
import hashlib
import warnings
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline
from pymongo import MongoClient
from tqdm import tqdm

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# CONFIG — edit these before running
# ─────────────────────────────────────────────
CONFIG = {
    "mongo_uri": "mongodb://localhost:27017/",
    "db_name": "cloud_monitoring",

    "metrics_collection": "cloud_account_data_collection_daily_updated",
    "alerts_collection": "cloud_account_activity_log_updated",

    # EDA (Part E) confirmed real volume in Nov 2025 — switched from Aug 2025
    "start_date": datetime(2025, 11, 1, tzinfo=timezone.utc),
    "end_date":   datetime(2025, 11, 30, 23, 59, 59, tzinfo=timezone.utc),

    # Raised from 500 -> 1000 to get a workable pretraining population
    "max_resources": 1000,

    # $sample oversampling factor before entity dedup (was 5x, EDA showed
    # too few unique entities survived dedup at 5x)
    "sample_multiplier": 20,

    "noise_fraction": 0.05,

    "anomaly_spike_multiplier": (3.0, 6.0),
    "anomaly_drop_multiplier":  (0.05, 0.2),
    "anomaly_duration_minutes": (15, 45),

    "output_dir": "./corpus_output",
    "output_filename": "pretrain_corpus.parquet",
}

# ─────────────────────────────────────────────
# STEP 1: Helpers
# ─────────────────────────────────────────────

def detect_cloud(doc: dict) -> str:
    """
    Infer cloud provider from document fields.

    EDA finding: metric docs from cloud_account_data_collection_daily_updated
    frequently lack `namespace`. The risk-scoring script (Step4b) correctly
    classified the full inventory (AWS 966K / OCI 32K / Azure 23K / GCP 160K)
    by leaning on category/uri/resource-style fields rather than namespace
    alone, so this fallback chain mirrors that approach.
    """
    ns   = str(doc.get("namespace", ""))
    rid  = str(doc.get("resourceId") or doc.get("element_id") or "")
    uri  = str(doc.get("uri", ""))
    cat  = str(doc.get("category", ""))
    comp = str(doc.get("component", ""))  # present in inventory-style docs

    # AWS signals: arn prefix, i-/sg-/vol- style ids, EC2 component/category
    if (rid.startswith("i-") or rid.startswith("sg-") or rid.startswith("vol-")
            or rid.startswith("arn:aws") or "AWS" in ns or "AWS" in uri
            or comp == "EC2" or "EC2" in cat or "AWS" in cat):
        return "AWS"

    # OCI signals: ocid prefix, oci_ namespace prefix
    if rid.startswith("ocid") or ns.lower().startswith("oci") or "OCI" in uri or "OCI" in cat:
        return "OCI"

    # Azure signals: /subscriptions/ path, Microsoft.* namespace, Azure category/uri
    if ("/subscriptions/" in rid or ns.startswith("Microsoft")
            or "Azure" in uri or "Azure" in cat or "Virtual_Machines" in cat):
        return "Azure"

    # GCP signals: compute.googleapis resource paths, GCP-tagged uri/category
    if "compute.googleapis" in rid or "GCP" in uri or "GCP" in cat or "projects/" in rid:
        return "GCP"

    return "Unknown"


def extract_hourly_values(metric_value_list: list) -> list:
    """Extract numeric average values from the metric_value array (AWS/Azure shapes)."""
    result = []
    for entry in metric_value_list:
        if not isinstance(entry, dict):
            result.append(None)
            continue
        val = entry.get("Average") or entry.get("average") or entry.get("Sum")
        try:
            result.append(float(val)) if val is not None else result.append(None)
        except (TypeError, ValueError):
            result.append(None)
    return result


def short_hash(s: str, length: int = 8) -> str:
    return hashlib.md5(s.encode()).hexdigest()[:length]


# ─────────────────────────────────────────────
# STEP 2: Pull metric seed data from MongoDB
# ─────────────────────────────────────────────

def pull_metric_seeds(db, cfg: dict) -> pd.DataFrame:
    """
    Query cloud_account_data_collection_daily_updated for the target month.
    Uses $sample at a higher multiplier (EDA showed 5x left too few unique
    entities after dedup) so we reliably reach max_resources entities.
    """
    col = db[cfg["metrics_collection"]]

    query = {
        "from_date": {
            "$gte": cfg["start_date"].replace(tzinfo=None),
            "$lte": cfg["end_date"].replace(tzinfo=None),
        },
        "metric_value": {"$exists": True, "$ne": []},
    }

    projection = {
        "_id": 0,
        "element_id": 1,
        "resourceId": 1,
        "category": 1,
        "component": 1,
        "metric": 1,
        "namespace": 1,
        "uri": 1,
        "resourceType": 1,
        "from_date": 1,
        "to_date": 1,
        "account_id": 1,
        "resource_name": 1,
        "metric_value": 1,
        "name": 1,
        "unit": 1,
    }

    print(f"\n[STEP 2] Querying metrics collection ({cfg['metrics_collection']})...")

    sample_size = cfg["max_resources"] * cfg["sample_multiplier"]
    cursor = col.aggregate([
        {"$match": query},
        {"$sample": {"size": sample_size}},
        {"$project": projection},
    ])

    rows = []
    for doc in tqdm(cursor, desc="  Loading metric docs", unit="doc", total=sample_size):
        eid = str(doc.get("element_id") or doc.get("resourceId") or "unknown")
        hourly_vals = extract_hourly_values(doc.get("metric_value", []))

        non_null = [v for v in hourly_vals if v is not None and v > 0]
        if len(non_null) < 3:
            continue

        cloud = detect_cloud(doc)
        rows.append({
            "entity_id":    eid,
            "entity_type":  str(doc.get("category", "Unknown")),
            "cloud":        cloud,
            "namespace":    str(doc.get("namespace", "")),
            "metric_name":  str(doc.get("metric", "unknown")),
            "date":         pd.Timestamp(doc["from_date"]).normalize(),
            "account_id":   str(doc.get("account_id", "")),
            "unit":         str(doc.get("unit", "")),
            "hourly_values": hourly_vals,
        })

    df = pd.DataFrame(rows)
    print(f"  Loaded {len(df):,} (resource, day, metric) seed records")

    if df.empty:
        print("  WARNING: No metric data found for the configured date range.")
        print("  Tip: Run the date-range diagnostic query (see comment at bottom of file)")
        return df

    unique_entities = df["entity_id"].unique()
    print(f"  Unique entities before capping: {len(unique_entities):,}")

    if cfg["max_resources"] and len(unique_entities) > cfg["max_resources"]:
        sampled = np.random.choice(unique_entities, cfg["max_resources"], replace=False)
        df = df[df["entity_id"].isin(sampled)].reset_index(drop=True)
        print(f"  Capped to {cfg['max_resources']} unique entities")

    print(f"  Final unique entities: {df['entity_id'].nunique():,}")
    print(f"  Unique metrics:        {df['metric_name'].nunique():,}")
    print(f"  Cloud distribution:    {df['cloud'].value_counts().to_dict()}")

    unknown_frac = (df["cloud"] == "Unknown").mean()
    if unknown_frac > 0.3:
        print(f"  NOTE: {unknown_frac:.0%} still Unknown — inspect a few raw docs "
              f"with cloud=='Unknown' to extend detect_cloud() further if needed.")

    return df


# ─────────────────────────────────────────────
# STEP 3: Pull alert events as anomaly anchors
# ─────────────────────────────────────────────

def pull_alert_anchors(db, cfg: dict) -> dict:
    """
    Query cloud_account_activity_log_updated for monitoring alerts in the period.

    Fix: event_creation_time is stored as a naive datetime in Mongo, but the
    original query sent timezone-aware bounds, which silently matched nothing.
    Bounds are now stripped of tzinfo before querying.

    Note (from EDA Part B): monitoring alert resource_ids are OCIDs
    (ocid1.instance.oc1...), while AWS/Azure metric entity_ids are
    i-xxxx / sg-xxxx / Azure resourceId paths. These namespaces don't
    overlap, so anchors will mostly match OCI entities in the metric
    seed set, not AWS/Azure ones. That's expected given the underlying
    data, not a bug in this query — flagged explicitly below.
    """
    col = db[cfg["alerts_collection"]]

    query = {
        "alert_type": "monitoring",
        "event_creation_time": {
            "$gte": cfg["start_date"].replace(tzinfo=None),
            "$lte": cfg["end_date"].replace(tzinfo=None),
        },
        "raw_data.resource_id": {"$exists": True},
    }

    projection = {
        "_id": 0,
        "event_creation_time": 1,
        "raw_data.resource_id": 1,
        "raw_data.alert_state": 1,
        "raw_data.metric_name": 1,
        "raw_data.type": 1,
        "raw_data.severity": 1,
    }

    print(f"\n[STEP 3] Querying alerts collection for anomaly anchors...")
    cursor = col.find(query, projection, limit=50000)

    anchors = {}
    count = 0
    for doc in cursor:
        rd = doc.get("raw_data", {})
        rid = rd.get("resource_id", "")
        if not rid:
            continue

        ts = doc.get("event_creation_time")
        if ts is None:
            continue
        ts = pd.Timestamp(ts, tz="UTC")

        transition  = rd.get("type", "")
        alert_state = rd.get("alert_state", "")
        if transition == "OK_TO_FIRING" or alert_state == "FIRING":
            atype = "spike"
        elif transition == "FIRING_TO_OK" or alert_state == "OK":
            atype = "recovery"
        else:
            atype = "spike"

        anchors.setdefault(rid, []).append((ts, atype))
        count += 1

    print(f"  Found {count:,} alert events across {len(anchors):,} unique resources")

    if count > 0:
        sample_ids = list(anchors.keys())[:3]
        is_ocid = all(rid.startswith("ocid") for rid in sample_ids)
        if is_ocid:
            print("  NOTE: anchor resource_ids are OCIDs — these will match OCI "
                  "entities in the metric seed set. AWS/Azure entities in this "
                  "corpus will mostly have is_anomaly=False, which is expected "
                  "and fine for contrastive pretraining (no labels required).")
    else:
        print("  WARNING: still 0 anchors. Check that alert_type=='monitoring' "
              "docs actually exist in this date range (see diagnostic at bottom of file).")

    return anchors


# ─────────────────────────────────────────────
# STEP 4: Minute-wise interpolation + noise
# ─────────────────────────────────────────────

def interpolate_to_minutes(
    hourly_values: list,
    date: pd.Timestamp,
    noise_fraction: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    vals = np.array([v if v is not None else np.nan for v in hourly_values], dtype=float)

    if len(vals) < 24:
        vals = np.concatenate([vals, np.full(24 - len(vals), np.nan)])
    vals = vals[:24]

    series = pd.Series(vals).interpolate(method="linear", limit_direction="both").fillna(method="bfill").fillna(method="ffill")
    vals = series.values

    hours = np.arange(24)
    hours_ext = np.concatenate([[-1], hours, [24]])
    vals_ext  = np.concatenate([[vals[-1]], vals, [vals[0]]])

    cs = CubicSpline(hours_ext, vals_ext, bc_type="not-a-knot")

    minute_positions = np.arange(1440) / 60.0
    minute_vals = cs(minute_positions)

    hourly_mean = np.mean(vals[vals > 0]) if np.any(vals > 0) else 1.0
    noise_std = noise_fraction * hourly_mean
    noise = rng.normal(0, noise_std, size=1440)
    minute_vals = np.clip(minute_vals + noise, 0, None)

    minute_timestamps = pd.date_range(start=date, periods=1440, freq="1min", tz="UTC")

    return pd.DataFrame({
        "timestamp":      minute_timestamps,
        "value":          minute_vals,
        "hour_of_day":    (np.arange(1440) // 60).astype(np.int8),
        "minute_of_hour": (np.arange(1440) % 60).astype(np.int8),
        "day_of_week":    date.day_of_week,
        "hour_anchor":    np.repeat(vals, 60),
    })


def inject_anomalies(
    minute_df: pd.DataFrame,
    entity_id: str,
    alert_anchors: dict,
    cfg: dict,
    rng: np.random.Generator,
) -> pd.DataFrame:
    minute_df = minute_df.copy()
    minute_df["is_anomaly"] = False
    minute_df["anomaly_type"] = ""

    anchors_for_entity = alert_anchors.get(entity_id, [])
    if not anchors_for_entity:
        return minute_df

    day_start = minute_df["timestamp"].iloc[0]
    day_end   = minute_df["timestamp"].iloc[-1]

    for (alert_ts, atype) in anchors_for_entity:
        if not (day_start <= alert_ts <= day_end):
            continue

        dur = rng.integers(*cfg["anomaly_duration_minutes"])
        window_start = alert_ts - pd.Timedelta(minutes=dur // 2)
        window_end   = alert_ts + pd.Timedelta(minutes=dur // 2)

        mask = (minute_df["timestamp"] >= window_start) & (minute_df["timestamp"] <= window_end)

        if atype == "spike":
            factor = rng.uniform(*cfg["anomaly_spike_multiplier"])
            minute_df.loc[mask, "value"] = minute_df.loc[mask, "value"] * factor
        elif atype == "recovery":
            factor = rng.uniform(*cfg["anomaly_drop_multiplier"])
            minute_df.loc[mask, "value"] = minute_df.loc[mask, "value"] * factor

        minute_df.loc[mask, "is_anomaly"] = True
        minute_df.loc[mask, "anomaly_type"] = atype

    return minute_df


# ─────────────────────────────────────────────
# STEP 5: Main corpus assembly
# ─────────────────────────────────────────────

def build_corpus(seed_df: pd.DataFrame, alert_anchors: dict, cfg: dict) -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    all_chunks = []

    print(f"\n[STEP 5] Generating minute-wise corpus...")
    print(f"  Seed rows to expand: {len(seed_df):,}")
    print(f"  Expected output rows: ~{len(seed_df) * 1440:,}")

    for idx, row in tqdm(seed_df.iterrows(), total=len(seed_df), desc="  Expanding rows", unit="seed"):
        try:
            min_df = interpolate_to_minutes(
                hourly_values=row["hourly_values"],
                date=row["date"],
                noise_fraction=cfg["noise_fraction"],
                rng=rng,
            )

            min_df = inject_anomalies(
                minute_df=min_df,
                entity_id=row["entity_id"],
                alert_anchors=alert_anchors,
                cfg=cfg,
                rng=rng,
            )

            min_df["entity_id"]   = row["entity_id"]
            min_df["entity_type"] = row["entity_type"]
            min_df["cloud"]       = row["cloud"]
            min_df["namespace"]   = row["namespace"]
            min_df["metric_name"] = row["metric_name"]
            min_df["account_id"]  = row["account_id"]
            min_df["unit"]        = row["unit"]

            all_chunks.append(min_df)

        except Exception:
            continue

    if not all_chunks:
        print("  ERROR: No chunks generated. Check seed data.")
        return pd.DataFrame()

    corpus = pd.concat(all_chunks, ignore_index=True)

    ordered_cols = [
        "entity_id", "entity_type", "cloud", "namespace", "metric_name",
        "timestamp", "value", "hour_anchor", "is_anomaly", "anomaly_type",
        "day_of_week", "hour_of_day", "minute_of_hour", "account_id", "unit",
    ]
    corpus = corpus[[c for c in ordered_cols if c in corpus.columns]]

    return corpus


# ─────────────────────────────────────────────
# STEP 6: Write output + summary
# ─────────────────────────────────────────────

def write_output(corpus: pd.DataFrame, cfg: dict):
    os.makedirs(cfg["output_dir"], exist_ok=True)
    out_path = os.path.join(cfg["output_dir"], cfg["output_filename"])

    print(f"\n[STEP 6] Writing corpus to {out_path} ...")
    corpus.to_parquet(out_path, index=False, engine="pyarrow", compression="snappy")

    size_mb = os.path.getsize(out_path) / (1024 ** 2)
    print(f"  Done. File size: {size_mb:.1f} MB")

    summary = {
        "total_rows":         len(corpus),
        "unique_entities":    int(corpus["entity_id"].nunique()),
        "unique_metrics":     int(corpus["metric_name"].nunique()),
        "cloud_distribution": corpus["cloud"].value_counts().to_dict(),
        "anomaly_rows":       int(corpus["is_anomaly"].sum()),
        "anomaly_fraction":   float(corpus["is_anomaly"].mean()),
        "date_range":         [str(corpus["timestamp"].min()), str(corpus["timestamp"].max())],
        "output_path":        out_path,
        "file_size_mb":       round(size_mb, 2),
    }

    summary_path = os.path.join(cfg["output_dir"], "corpus_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 60)
    print("CORPUS SUMMARY")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k:<25}: {v}")
    print("=" * 60)

    return summary


# ─────────────────────────────────────────────
# FALLBACK: Synthetic-only mode (no MongoDB)
# ─────────────────────────────────────────────

def generate_synthetic_seeds(cfg: dict) -> pd.DataFrame:
    print("\n[FALLBACK] Generating synthetic seed data (no DB connection needed)...")
    rng = np.random.default_rng(42)

    archetypes = [
        ("Instances",        "AWS",   "AWS/EC2",                   "NetworkIn",            80000, "business_hours"),
        ("Instances",        "AWS",   "AWS/EC2",                   "CPUUtilization",       35.0,   "business_hours"),
        ("Instances",        "AWS",   "AWS/EC2",                   "NetworkOut",           60000, "business_hours"),
        ("Virtual_Machines", "Azure", "Microsoft.Compute",         "Network In",           50000, "business_hours"),
        ("Virtual_Machines", "Azure", "Microsoft.Compute",         "Percentage CPU",       40.0,   "business_hours"),
        ("Private_Endpoint",  "Azure", "Microsoft.Network",        "PEBytesIn",            5000,  "always_on"),
        ("oci_connector",    "OCI",   "oci_service_connector_hub", "BytesReadFromSource",  200,   "always_on"),
        ("oci_connector",    "OCI",   "oci_service_connector_hub", "BytesWrittenToTarget", 180,   "always_on"),
        ("Security_Groups",  "AWS",   "AWS/EC2",                   "NetworkPackets",       1000,  "always_on"),
    ]

    def make_daily_pattern(pattern_type, base_mean, rng):
        if pattern_type == "business_hours":
            weights = np.array([
                0.1, 0.1, 0.1, 0.1, 0.15, 0.2,
                0.4, 0.7, 0.9, 1.0, 1.0, 1.0,
                0.95, 1.0, 1.0, 0.95, 0.9, 0.85,
                0.7, 0.5, 0.35, 0.25, 0.15, 0.1,
            ])
        else:
            weights = np.array([
                0.7, 0.65, 0.6, 0.6, 0.65, 0.7,
                0.8, 0.9, 1.0, 1.0, 1.0, 1.0,
                1.0, 1.0, 1.0, 0.95, 0.9, 0.9,
                0.85, 0.8, 0.8, 0.75, 0.75, 0.7,
            ])
        day_factor = rng.uniform(0.85, 1.15)
        vals = base_mean * weights * day_factor
        noise = rng.normal(0, base_mean * 0.03, size=24)
        return list(np.clip(vals + noise, 0, None))

    n_resources = cfg.get("max_resources") or 200
    n_per_arch = max(1, n_resources // len(archetypes))

    rows = []
    start = cfg["start_date"].replace(tzinfo=None)
    end   = cfg["end_date"].replace(tzinfo=None)
    date_range = pd.date_range(start, end, freq="D")

    for (etype, cloud, ns, metric, base_mean, pattern) in archetypes:
        for i in range(n_per_arch):
            entity_id = f"synthetic-{cloud.lower()}-{metric.lower().replace(' ', '_')}-{i:04d}"
            entity_mean = base_mean * rng.uniform(0.5, 2.0)

            for date in date_range:
                rows.append({
                    "entity_id":     entity_id,
                    "entity_type":   etype,
                    "cloud":         cloud,
                    "namespace":     ns,
                    "metric_name":   metric,
                    "date":          pd.Timestamp(date),
                    "account_id":    f"synth-account-{i % 5:02d}",
                    "unit":          "Bytes" if "Bytes" in metric or "Network" in metric else "Percent",
                    "hourly_values": make_daily_pattern(pattern, entity_mean, rng),
                })

    df = pd.DataFrame(rows)
    print(f"  Generated {len(df):,} synthetic seed rows for {df['entity_id'].nunique()} entities")
    return df


def generate_synthetic_anchors(seed_df: pd.DataFrame, cfg: dict) -> dict:
    rng = np.random.default_rng(99)
    anchors = {}

    entities = seed_df["entity_id"].unique()
    for eid in entities:
        entity_rows = seed_df[seed_df["entity_id"] == eid]
        dates = entity_rows["date"].unique()

        for date in dates:
            if rng.random() < 0.10:
                hour   = int(rng.integers(8, 20))
                minute = int(rng.integers(0, 60))
                ts = pd.Timestamp(date, tz="UTC") + pd.Timedelta(hours=hour, minutes=minute)
                atype = "spike" if rng.random() < 0.7 else "recovery"
                anchors.setdefault(eid, []).append((ts, atype))

    total_anchors = sum(len(v) for v in anchors.values())
    print(f"  Generated {total_anchors:,} synthetic anomaly anchors across {len(anchors):,} entities")
    return anchors


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("CORPUS GENERATOR — Contrastive SSL Pretraining (v2)")
    print(f"Target period: {CONFIG['start_date'].date()} → {CONFIG['end_date'].date()}")
    print("=" * 60)

    use_synthetic = False

    try:
        client = MongoClient(CONFIG["mongo_uri"], serverSelectionTimeoutMS=5000)
        client.server_info()
        db = client[CONFIG["db_name"]]
        print(f"\n[STEP 1] Connected to MongoDB: {CONFIG['mongo_uri']}")
        print(f"  Database: {CONFIG['db_name']}")
        print(f"  Collections: {db.list_collection_names()}")

        seed_df = pull_metric_seeds(db, CONFIG)

        if seed_df.empty:
            print("  No seed data found — switching to synthetic mode.")
            use_synthetic = True
        else:
            alert_anchors = pull_alert_anchors(db, CONFIG)

    except Exception as e:
        print(f"\n[STEP 1] MongoDB connection failed: {e}")
        print("  Switching to synthetic-only mode.")
        use_synthetic = True

    if use_synthetic:
        seed_df       = generate_synthetic_seeds(CONFIG)
        alert_anchors = generate_synthetic_anchors(seed_df, CONFIG)

    corpus = build_corpus(seed_df, alert_anchors, CONFIG)

    if corpus.empty:
        print("ERROR: Corpus is empty. Check your date range and collection names.")
        return

    write_output(corpus, CONFIG)

    print("\nDone! Next steps:")
    print("  1. Load corpus with: pd.read_parquet('./corpus_output/pretrain_corpus.parquet')")
    print("  2. Feed into the TSTCC windowing + contrastive encoder pipeline")
    print("  3. Each entity_id becomes one 'entity' in the dynamic embedding store")


if __name__ == "__main__":
    main()

# ─────────────────────────────────────────────
# DIAGNOSTIC (run separately if entity counts are still low)
# ─────────────────────────────────────────────
# from pymongo import MongoClient
# db = MongoClient()["cloud_monitoring"]
# col = db["cloud_account_data_collection_daily_updated"]
# oldest = col.find_one(sort=[("from_date", 1)])
# newest = col.find_one(sort=[("from_date", -1)])
# print(oldest["from_date"], "->", newest["from_date"])
#
# acol = db["cloud_account_activity_log_updated"]
# print(acol.count_documents({"alert_type": "monitoring",
#       "event_creation_time": {"$gte": datetime(2025,11,1), "$lte": datetime(2025,11,30)}}))