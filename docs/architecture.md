# System architecture

```mermaid
flowchart LR
    telemetry["Cloud telemetry and event producers"]

    subgraph p0["Phase 0 — Streaming foundation"]
        ingest["Validate and normalize events"]
        buckets["Time buckets and rolling baselines"]
        scoring["Per-metric anomaly scoring"]
        ingest --> buckets --> scoring
    end

    subgraph p1["Phase 1 — Offline representation learning"]
        history["Historical telemetry corpus"]
        train["Augment pairs and train TSTCC encoder"]
        artifacts["Versioned model bundle<br/>encoder + feature_meta.json + FAISS index"]
        history --> train --> artifacts
    end

    subgraph p2["Phase 2 — Online detection and alerting"]
        encode["Encode records and entity embeddings"]
        detect["Deviation, drift, and episode analysis"]
        alert["Correlate, prioritize, and notify"]
        encode --> detect --> alert
    end

    subgraph p3["Phase 3 — Tenant-scoped investigation"]
        platform["Platform data<br/>tenants, incidents, RCA cases"]
        rca["Evidence and deterministic RCA"]
        guidance["Knowledge base guidance<br/>explanations and recommended checks"]
        dashboard["Incident investigation dashboard"]
        platform --> rca --> guidance --> dashboard
    end

    telemetry --> ingest
    phase2_events["Validated event batches"] --> encode
    artifacts --> encode
    alert --> platform
    guidance --> notifications["Configured notification channels"]
```

Phase 0 provides a statistical streaming/scoring path, and Phase 1 independently
trains a representation model from historical data. Phase 2 consumes validated
event batches and a registered Phase 1 bundle; Phase 0 scores are not currently
passed into Phase 2 or attached to an `RCACase`. Phase 3 turns Phase 2 alert
evidence into tenant-scoped incidents, deterministic RCA, static knowledge
guidance, and analyst-facing views. Notification delivery is configured per
tenant and channel.
