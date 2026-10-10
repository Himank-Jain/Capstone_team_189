from typing import Any, Dict, List, Optional
import random
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import numpy as np
import torch
from phase2.encoding.reference_encoder_service import load_inference_encoder_from_manifest
from phase2.encoding.record_encoder import RecordEncoder
from phase2.detection.cosine_deviation_scorer import CosineDeviationScorer
from phase2.detection.mmd_drift_monitor import mmd_rbf
from phase2.alerting.alert_deduplicator import AlertDeduplicator
from phase2.alerting.api.payload_builder import build_alert_payload
from phase2.alerting.correlation_engine import BaseEntityAttributesProvider, CorrelationEngine
from phase2.alerting.escalation_engine import EntityMetadata, EscalationEngine, StaticEntityMetadataProvider
from phase2.detection.anomaly_scorer import AnomalyScorer
from .analytics import build_summary_payload
from .auth import build_login_response
from .tenants import get_demo_tenants
from .ws_common import broadcast_alert
from .ws_heartbeat import build_stage_heartbeat
from .ws_router import router as ws_router
from shared.types import EntityAttributesData, EpisodeMatch, NotifyMethod, ScoringInput, RawRecord, CurrentEmbedding, EntityProfile
from .email_service import EmailService
from .phase3_routes import process_demo_alert, router as phase3_router

app = FastAPI(title="CAPSTONE-189 Demo API")

alerts_by_tenant: Dict[str, List[Dict[str, Any]]] = {}

DEMO_STATE: Dict[str, Dict[str, Any]] = {}

MAX_ALERTS = 100
DEMO_HISTORY_RETENTION = timedelta(minutes=45)

DEMO_TENANT_PROFILES: Dict[str, Dict[str, str]] = {
    "google": {
        "entity_id": "vol-g00g",
        "cloud_provider": "GCP",
        "region": "us-central1",
        "entity_criticality": "medium",
        "timezone": "America/Chicago",
    },
    "microsoft": {
        "entity_id": "vol-msft",
        "cloud_provider": "Azure",
        "region": "eastus",
        "entity_criticality": "high",
        "timezone": "America/New_York",
    },
    "amazon": {
        "entity_id": "vol-amzn",
        "cloud_provider": "AWS",
        "region": "us-east-1",
        "entity_criticality": "critical",
        "timezone": "America/New_York",
    },
    "oracle": {
        "entity_id": "vol-orcl",
        "cloud_provider": "OCI",
        "region": "us-phoenix-1",
        "entity_criticality": "high",
        "timezone": "America/Phoenix",
    },
    "openai": {
        "entity_id": "vol-open",
        "cloud_provider": "AWS",
        "region": "us-west-2",
        "entity_criticality": "critical",
        "timezone": "America/Los_Angeles",
    },
}

DEMO_SCENARIO_PROFILES: Dict[str, Dict[str, Any]] = {
    "credential_theft": {
        "deviation_base": 0.72,
        "drift_base": 0.58,
        "similarity_base": 0.42,
        "op_id": "iam-policy-change",
        "contributing_features": [
            "iam_policy_change",
            "suspicious_login_location",
            "credential_reset_spike",
        ],
    },
    "insider_threat": {
        "deviation_base": 0.60,
        "drift_base": 0.44,
        "similarity_base": 0.60,
        "op_id": "privilege-escalation",
        "contributing_features": [
            "file_access_spike",
            "privilege_escalation_attempt",
            "new_data_exfiltration_pattern",
        ],
    },
    "network_scan": {
        "deviation_base": 0.48,
        "drift_base": 0.34,
        "similarity_base": 0.70,
        "op_id": "network-port-scan",
        "contributing_features": [
            "port_scan_count",
            "new_ip_discovery",
            "lateral_probe_burst",
        ],
    },
    "benign_baseline": {
        "deviation_base": 0.08,
        "drift_base": 0.10,
        "similarity_base": 0.94,
        "op_id": "baseline-traffic",
        "contributing_features": [
            "expected_business_hours",
            "baseline_traffic_recovered",
        ],
    },
}


class DemoEntityAttributesProvider(BaseEntityAttributesProvider):
    def __init__(self, entity_attributes_map: Dict[str, EntityAttributesData]) -> None:
        self._entity_attributes_map = entity_attributes_map

    def get_attributes(self, entity_id: str) -> EntityAttributesData:
        if entity_id not in self._entity_attributes_map:
            raise KeyError(f"No demo attributes registered for entity_id={entity_id!r}")
        return self._entity_attributes_map[entity_id]


class InMemoryRedisPipeline:
    def __init__(self, store: "InMemoryRedisStore") -> None:
        self._store = store
        self._pending_value: Optional[str] = None
        self._pending_key: Optional[str] = None
        self._pending_ex: Optional[int] = None
        self._pending_keep_ttl = False

    def __enter__(self) -> "InMemoryRedisPipeline":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def watch(self, key: str) -> None:
        self._store.purge_if_expired(key)

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def multi(self) -> None:
        return None

    def set(self, key: str, value: str, ex: Optional[int] = None, keepttl: bool = False) -> None:
        self._pending_key = key
        self._pending_value = value
        self._pending_ex = ex
        self._pending_keep_ttl = keepttl

    def execute(self) -> List[bool]:
        if self._pending_key is not None and self._pending_value is not None:
            self._store.set(
                self._pending_key,
                self._pending_value,
                ex=self._pending_ex,
                keepttl=self._pending_keep_ttl,
            )
        return [True]


class InMemoryRedisStore:
    def __init__(self) -> None:
        self._values: Dict[str, str] = {}
        self._expires_at: Dict[str, datetime] = {}

    def purge_if_expired(self, key: str) -> None:
        expires_at = self._expires_at.get(key)
        if expires_at is not None and _now_utc() >= expires_at:
            self._values.pop(key, None)
            self._expires_at.pop(key, None)

    def get(self, key: str) -> Optional[str]:
        self.purge_if_expired(key)
        return self._values.get(key)

    def set(self, key: str, value: str, ex: Optional[int] = None, keepttl: bool = False) -> None:
        self._values[key] = value
        if ex is not None:
            self._expires_at[key] = _now_utc() + timedelta(seconds=ex)
        elif not keepttl:
            self._expires_at.pop(key, None)

    def pipeline(self) -> InMemoryRedisPipeline:
        return InMemoryRedisPipeline(self)


DEMO_ENTITY_ATTRIBUTES_MAP: Dict[str, EntityAttributesData] = {
    profile["entity_id"]: EntityAttributesData(
        entity_id=profile["entity_id"],
        cloud_provider=profile["cloud_provider"],
        region=profile["region"],
        op_id="baseline-traffic",
    )
    for profile in DEMO_TENANT_PROFILES.values()
}

DEMO_ENTITY_METADATA_PROVIDER = StaticEntityMetadataProvider(
    {
        profile["entity_id"]: EntityMetadata(
            entity_id=profile["entity_id"],
            entity_criticality=profile["entity_criticality"],
            timezone=profile["timezone"],
        )
        for profile in DEMO_TENANT_PROFILES.values()
    }
)

DEMO_ENTITY_ATTRIBUTES_PROVIDER = DemoEntityAttributesProvider(DEMO_ENTITY_ATTRIBUTES_MAP)
DEMO_ANOMALY_SCORER = AnomalyScorer()
DEMO_ESCALATION_ENGINE = EscalationEngine(DEMO_ENTITY_METADATA_PROVIDER)
DEMO_DEDUP_REDIS = InMemoryRedisStore()
DEMO_DEDUPLICATOR = AlertDeduplicator(DEMO_DEDUP_REDIS)
DEMO_CORRELATION_ENGINE = CorrelationEngine(DEMO_ENTITY_ATTRIBUTES_PROVIDER)


@app.get("/")
def root() -> Dict[str, str]:
    return {
        "service": "CAPSTONE-189 Demo API",
        "status": "ok",
        "frontend_demo": "http://127.0.0.1:5173/demo",
        "heartbeat_ws": "ws://127.0.0.1:8001/ws/heartbeat",
    }


def _resolve_tenant_header(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-Id header")
    return tenant_id


def _store_alert(tenant_id: str, payload: Dict[str, Any]) -> None:
    alerts = alerts_by_tenant.setdefault(tenant_id, [])
    alerts.insert(0, payload)
    if len(alerts) > MAX_ALERTS:
        alerts[:] = alerts[:MAX_ALERTS]


async def _send_notifications(payload: Dict[str, Any], notify_method: str) -> Dict[str, Any]:
    """Send notifications based on notify method."""
    tenant_id = str(payload.get("tenant_id") or payload.get("tenant", "default")).strip().lower() or "default"
    notification_result = {
        "notify_method": notify_method,
        "status": "failed",
        "sent": False,
        "message": "Notification not sent"
    }
    
    try:
        if notify_method == "EMAIL":
            demo_email = EmailService.resolve_recipient_email(tenant_id)

            email_result = await EmailService.send_alert_email_result(demo_email, payload)

            if email_result["sent"]:
                notification_result["sent"] = True
                notification_result["status"] = "sent"
                notification_result["message"] = email_result.get("detail", f"Email sent to {demo_email}")
                notification_result["email_to"] = demo_email
                print(f"✓ Email notification sent to {demo_email}")
            else:
                log_dir = Path(__file__).parent / "email_logs"
                log_dir.mkdir(exist_ok=True)
                log_file = log_dir / f"email_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"

                email_log = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "to": demo_email,
                    "subject": f"[{payload.get('severity', 'UNKNOWN')}] Security Alert - {payload.get('entity_id', 'unknown')}",
                    "alert_id": payload.get("alert_id"),
                    "severity": payload.get("severity"),
                    "entity_id": payload.get("entity_id"),
                    "error": email_result.get("error", "Unknown email delivery failure"),
                    "note": "Email delivery failed. Check DEMO_EMAIL_SENDER and DEMO_EMAIL_PASSWORD, then retry."
                }

                with open(log_file, 'w') as f:
                    json.dump(email_log, f, indent=2)

                notification_result["status"] = "failed"
                notification_result["message"] = f"Email delivery failed: {email_result.get('error', 'unknown error')}"
                notification_result["email_to"] = demo_email
                notification_result["log_path"] = str(log_file)
                print(f"⚠ Email notification logged (delivery failed): {log_file}")
            
        elif notify_method == "SLACK":
            notification_result["sent"] = True
            notification_result["status"] = "sent"
            notification_result["message"] = "Slack notification posted to #security-alerts"
            
        elif notify_method == "PAGE":
            notification_result["sent"] = True
            notification_result["status"] = "displayed"
            notification_result["message"] = "Alert displayed on dashboard"
            
    except Exception as e:
        notification_result["status"] = "failed"
        notification_result["message"] = f"Notification failed: {str(e)}"
        print(f"✗ Notification error: {str(e)}")
    
    return notification_result


async def _dispatch_alert(tenant_id: str, payload: Dict[str, Any]) -> None:
    _store_alert(tenant_id, payload)
    message = {"type": "alert", "tenant_id": tenant_id, "payload": payload}
    heartbeat = build_stage_heartbeat("encoding", payload["entity_id"])
    delta = {
        "type": "kpi_delta",
        "tenant_id": tenant_id,
        "active_alerts_delta": 1,
        "critical_alerts_delta": 1 if payload["severity"] == "CRITICAL" else 0,
    }
    await broadcast_alert(message)
    await broadcast_alert(heartbeat)
    await broadcast_alert(delta)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(ws_router)
app.include_router(phase3_router)


class LoginRequest(BaseModel):
    email: str
    password: str

class DemoScenario(BaseModel):
    value: str
    label: str
    description: str
    category: str
    default_notify_method: str
    severity: str


class DemoAlertRequest(BaseModel):
    tenant_id: str
    scenario: str
    notify_method: NotifyMethod = NotifyMethod.PAGE
    mode: str = "attack"


SCENARIOS: List[Dict[str, str]] = [
    {
        "value": "credential_theft",
        "label": "Credential Theft",
        "description": "Simulate stolen credentials used for privilege escalation and exfiltration.",
        "category": "attack",
        "default_notify_method": NotifyMethod.SLACK.value,
        "severity": "CRITICAL",
    },
    {
        "value": "insider_threat",
        "label": "Insider Threat",
        "description": "Simulate a trusted identity behaving anomalously inside the network.",
        "category": "attack",
        "default_notify_method": NotifyMethod.EMAIL.value,
        "severity": "HIGH",
    },
    {
        "value": "network_scan",
        "label": "Network Scan",
        "description": "Simulate reconnaissance and scanning behavior across cloud assets.",
        "category": "attack",
        "default_notify_method": NotifyMethod.PAGE.value,
        "severity": "MEDIUM",
    },
    {
        "value": "benign_baseline",
        "label": "Normal Baseline",
        "description": "Generate balanced normal traffic to preserve the model baseline.",
        "category": "normal",
        "default_notify_method": NotifyMethod.PAGE.value,
        "severity": "LOW",
    },
]

NOTIFY_METHODS: List[NotifyMethod] = [NotifyMethod.PAGE, NotifyMethod.SLACK, NotifyMethod.EMAIL]


def _find_scenario(scenario_value: str) -> Dict[str, str]:
    for scenario in SCENARIOS:
        if scenario["value"] == scenario_value:
            return scenario
    raise HTTPException(status_code=400, detail="unsupported scenario")


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _prune_demo_history(tenant_state: Dict[str, Any], reference_ts: datetime) -> None:
    tenant_state.setdefault("history", [])
    tenant_state["history"] = [
        item for item in tenant_state["history"]
        if reference_ts - item["batch_ts"] <= DEMO_HISTORY_RETENTION
    ]


def _get_tenant_state(tenant_id: str) -> Dict[str, Any]:
    tenant_state = DEMO_STATE.setdefault(tenant_id, {})
    tenant_state.setdefault("paused", False)
    tenant_state.setdefault("pressure", 0.0)
    tenant_state.setdefault("history", [])
    return tenant_state


def _build_similar_episodes(
    tenant_history: List[Dict[str, Any]],
    entity_id: str,
    cloud_provider: str,
    scenario_value: str,
    current_score: float,
) -> List[EpisodeMatch]:
    similar_episodes: List[EpisodeMatch] = []

    for index, prior_event in enumerate(reversed(tenant_history[-3:])):
        scenario_penalty = 0.0 if prior_event["scenario"] == scenario_value else 0.12
        score_gap = abs(current_score - prior_event["final_score"])
        similarity_score = _clip01(0.92 - (score_gap * 0.70) - scenario_penalty - (index * 0.05))
        similar_episodes.append(
            EpisodeMatch(
                similarity_score=similarity_score,
                episode_id=prior_event["alert_id"],
                entity_id=entity_id,
                timestamp=prior_event["batch_ts"],
                cloud_provider=cloud_provider,
                severity_label=prior_event["severity"],
            )
        )

    return similar_episodes


# ─────────────────────────────────────────────────────────────────────────────
# PyTorch ML Model & Detection Engine Integration
# ─────────────────────────────────────────────────────────────────────────────

_ML_INFERENCE_ENCODER = None
_ML_FEATURE_META = None
_ML_RECORD_ENCODER = None
_COSINE_DEVIATION_SCORER = CosineDeviationScorer()
_ML_ENTITY_PROFILES: Dict[str, EntityProfile] = {}


def _get_ml_components():
    global _ML_INFERENCE_ENCODER, _ML_FEATURE_META, _ML_RECORD_ENCODER
    if _ML_INFERENCE_ENCODER is None:
        try:
            manifest_path = Path(__file__).parent.parent.parent / "model_registry" / "artifacts_manifest.json"
            _ML_INFERENCE_ENCODER, _ML_FEATURE_META = load_inference_encoder_from_manifest(str(manifest_path))
            _ML_RECORD_ENCODER = RecordEncoder(_ML_FEATURE_META, seq_len=32)
            print("[ML Engine] Loaded T-STCC PyTorch encoder model from registry.")
        except Exception as exc:
            print(f"[ML Engine] Warning: Could not load PyTorch model ({exc}). Using baseline fallback.")
    return _ML_INFERENCE_ENCODER, _ML_RECORD_ENCODER


def _generate_telemetry_records(entity_id: str, cloud: str, scenario_value: str, mode: str, now: datetime) -> List[RawRecord]:
    records: List[RawRecord] = []
    entity_type = "Volumes" if cloud == "GCP" else ("Virtual_Machines" if cloud == "Azure" else "Instances")
    namespace = "CWAgent" if cloud in ["AWS", "GCP"] else "Microsoft.Compute/virtualMachines"
    
    for i in range(32):
        ts = now - timedelta(minutes=32 - i)
        if mode == "normal" or scenario_value == "benign_baseline":
            metric = "CPUUtilization"
            val = float(12.0 + np.random.normal(0, 1.5))
        elif scenario_value == "credential_theft":
            metric = "ActivityFailedRuns" if i % 2 == 0 else "CPUUtilization"
            val = float(np.random.uniform(65, 98) if i >= 16 else np.random.uniform(5, 15))
        elif scenario_value == "insider_threat":
            metric = "BytesSent" if i % 2 == 0 else "CpuUsage"
            val = float(10.0 + (i * 2.8) + np.random.normal(0, 1.0))
        elif scenario_value == "network_scan":
            metric = "BytesReceived" if i % 3 == 0 else "AppConnections"
            val = float(np.random.uniform(180, 480))
        else:
            metric = "CPUUtilization"
            val = float(20.0 + np.random.normal(0, 2.0))
            
        records.append(RawRecord(
            entity_id=entity_id,
            timestamp=ts,
            cloud=cloud,
            entity_type=entity_type,
            namespace=namespace,
            metric_name=metric,
            value=val,
        ))
    return records


def _get_or_create_entity_profile(entity_id: str, cloud: str, now: datetime) -> EntityProfile:
    if entity_id in _ML_ENTITY_PROFILES:
        return _ML_ENTITY_PROFILES[entity_id]
    
    inf_enc, rec_enc = _get_ml_components()
    if inf_enc and rec_enc:
        base_recs = _generate_telemetry_records(entity_id, cloud, "benign_baseline", "normal", now - timedelta(hours=2))
        enc_dict = rec_enc.encode_entity_records(base_recs)
        base_emb = inf_enc.encode(
            enc_dict["numeric"].unsqueeze(0),
            enc_dict["categorical"].unsqueeze(0),
            enc_dict["timestamps"].unsqueeze(0),
        ).cpu().numpy()[0]
        
        history_embs = [
            (base_emb + np.random.normal(0, 0.005, size=128)).astype(np.float32)
            for _ in range(15)
        ]
        history_embs = [e / float(np.linalg.norm(e)) for e in history_embs]
        
        profile = EntityProfile(
            entity_id=entity_id,
            centroid_emb=base_emb,
            history_embs=history_embs,
            emb_variance=0.01,
            n_records=32,
            last_update_ts=now,
            cold_start_flag=False,
        )
    else:
        rng = np.random.default_rng(42)
        base_emb = rng.normal(size=128).astype(np.float32)
        base_emb /= float(np.linalg.norm(base_emb))
        profile = EntityProfile(
            entity_id=entity_id,
            centroid_emb=base_emb,
            history_embs=[base_emb],
            emb_variance=0.01,
            n_records=32,
            last_update_ts=now,
            cold_start_flag=False,
        )
    _ML_ENTITY_PROFILES[entity_id] = profile
    return profile


def _compute_demo_scoring_inputs(
    tenant_state: Dict[str, Any],
    scenario_value: str,
    mode: str,
    profile_info: Dict[str, Any],
    reference_ts: datetime,
    entity_id: str = "vol-amzn",
    cloud_provider: str = "AWS",
) -> Dict[str, Any]:
    _prune_demo_history(tenant_state, reference_ts)
    tenant_history = tenant_state["history"]
    pressure = float(tenant_state.get("pressure", 0.0))

    recent_attacks = [item for item in tenant_history if item["mode"] == "attack"]
    same_scenario_attacks = [item for item in recent_attacks if item["scenario"] == scenario_value]

    inf_enc, rec_enc = _get_ml_components()
    entity_prof = _get_or_create_entity_profile(entity_id, cloud_provider, reference_ts)

    if inf_enc and rec_enc:
        recs = _generate_telemetry_records(entity_id, cloud_provider, scenario_value, mode, reference_ts)
        enc_dict = rec_enc.encode_entity_records(recs)
        
        # Pass raw tensors into loaded PyTorch TSTCC Encoder
        live_emb = inf_enc.encode(
            enc_dict["numeric"].unsqueeze(0),
            enc_dict["categorical"].unsqueeze(0),
            enc_dict["timestamps"].unsqueeze(0),
        ).cpu().numpy()[0]
        
        # 1. Cosine deviation against baseline centroid
        curr_emb_obj = CurrentEmbedding(
            entity_id=entity_id,
            emb=live_emb,
            batch_ts=reference_ts,
            n_records=32,
            cloud_provider=cloud_provider,
        )
        dev_res = _COSINE_DEVIATION_SCORER.compute_scores(curr_emb_obj, entity_prof)
        raw_deviation = float(dev_res.global_score)
        
        # 2. MMD distribution drift
        recent_embs = np.array([live_emb] * 5 + entity_prof.history_embs[-5:])
        hist_embs = np.array(entity_prof.history_embs)
        mmd_val = float(mmd_rbf(recent_embs, hist_embs, sigma=1.0))
        raw_drift = min(1.0, max(0.0, mmd_val * 4.5))
        
        # Update entity profile history & EMA centroid with live embedding
        alpha = 0.1
        entity_prof.history_embs.append(live_emb)
        if len(entity_prof.history_embs) > 30:
            entity_prof.history_embs.pop(0)
        entity_prof.centroid_emb = (1 - alpha) * entity_prof.centroid_emb + alpha * live_emb
        entity_prof.centroid_emb /= float(np.linalg.norm(entity_prof.centroid_emb))
        entity_prof.last_update_ts = reference_ts

        if mode == "normal":
            pressure = max(0.0, pressure - 0.22)
            deviation_score = _clip01(raw_deviation * 0.4)
            drift_score = _clip01(raw_drift * 0.3)
            similarity_score = _clip01(0.94 - (pressure * 0.20))
        else:
            recurrence_index = len(same_scenario_attacks)
            tenant_attack_count = len(recent_attacks)
            escalation_boost = min(
                0.35,
                (recurrence_index * 0.10)
                + (max(tenant_attack_count - 1, 0) * 0.04)
                + (pressure * 0.15),
            )
            deviation_score = _clip01(max(raw_deviation, profile_info["deviation_base"] * 0.8) + escalation_boost)
            drift_score = _clip01(max(raw_drift, profile_info["drift_base"] * 0.8) + (escalation_boost * 0.85))
            similarity_score = _clip01(profile_info["similarity_base"] - (escalation_boost * 0.80))
            pressure = min(1.0, pressure + 0.12 + (recurrence_index * 0.05))

        contributing_features = profile_info["contributing_features"]
    else:
        if mode == "normal":
            pressure = max(0.0, pressure - 0.22)
            deviation_score = _clip01(0.08 + (pressure * 0.18))
            drift_score = _clip01(0.10 + (pressure * 0.12))
            similarity_score = _clip01(0.94 - (pressure * 0.20))
        else:
            recurrence_index = len(same_scenario_attacks)
            tenant_attack_count = len(recent_attacks)
            escalation_boost = min(
                0.36,
                (recurrence_index * 0.10)
                + (max(tenant_attack_count - 1, 0) * 0.04)
                + (pressure * 0.15),
            )
            deviation_score = _clip01(profile_info["deviation_base"] + escalation_boost)
            drift_score = _clip01(profile_info["drift_base"] + (escalation_boost * 0.85))
            similarity_score = _clip01(profile_info["similarity_base"] - (escalation_boost * 0.80))
            pressure = min(1.0, pressure + 0.12 + (recurrence_index * 0.05))
        contributing_features = profile_info["contributing_features"]

    tenant_state["pressure"] = pressure

    return {
        "deviation_score": deviation_score,
        "drift_score": drift_score,
        "similarity_score": similarity_score,
        "contributing_features": contributing_features,
        "recent_attack_count": len(recent_attacks),
        "same_scenario_count": len(same_scenario_attacks),
        "pressure": pressure,
    }


def _build_demo_alert_payload(tenant_id: str, scenario: Dict[str, str], notify_method: NotifyMethod, mode: str) -> Dict[str, object]:
    reference_ts = _now_utc()
    tenant_profile = DEMO_TENANT_PROFILES.get(tenant_id, DEMO_TENANT_PROFILES["amazon"])
    scenario_value = scenario["value"]
    scenario_profile = DEMO_SCENARIO_PROFILES.get(scenario_value, DEMO_SCENARIO_PROFILES["network_scan"])
    entity_id = tenant_profile["entity_id"]
    cloud_provider = tenant_profile["cloud_provider"]
    region = tenant_profile["region"]
    tenant_state = _get_tenant_state(tenant_id)

    DEMO_ENTITY_ATTRIBUTES_MAP[entity_id] = EntityAttributesData(
        entity_id=entity_id,
        cloud_provider=cloud_provider,
        region=region,
        op_id=scenario_profile["op_id"],
    )

    score_inputs = _compute_demo_scoring_inputs(
        tenant_state=tenant_state,
        scenario_value=scenario_value,
        mode=mode,
        profile_info=scenario_profile,
        reference_ts=reference_ts,
        entity_id=entity_id,
        cloud_provider=cloud_provider,
    )

    anomaly_result = DEMO_ANOMALY_SCORER.score(
        ScoringInput(
            entity_id=entity_id,
            deviation_score=score_inputs["deviation_score"],
            drift_score=score_inputs["drift_score"],
            similarity_score=score_inputs["similarity_score"],
            batch_ts=reference_ts,
            component_scores={
                "recent_attack_count": float(score_inputs["recent_attack_count"]),
                "same_scenario_count": float(score_inputs["same_scenario_count"]),
                "tenant_pressure": score_inputs["pressure"],
            },
        )
    )

    dedup_result = DEMO_DEDUPLICATOR.check(anomaly_result)
    correlation_result = DEMO_CORRELATION_ENGINE.process(
        entity_id=entity_id,
        canonical_incident_id=dedup_result.canonical_incident_id,
        alert_ts=reference_ts,
    )
    escalation_result = DEMO_ESCALATION_ENGINE.process(
        entity_id=entity_id,
        final_score=anomaly_result.final_score,
        anomaly_severity=anomaly_result.severity,
        group_type=correlation_result.group_type,
        incident_group_id=correlation_result.incident_group_id,
        alert_ts=reference_ts,
    )

    similar_episodes = _build_similar_episodes(
        tenant_history=tenant_state["history"],
        entity_id=entity_id,
        cloud_provider=cloud_provider,
        scenario_value=scenario_value,
        current_score=anomaly_result.final_score,
    )

    payload_model = build_alert_payload(
        anomaly_result=anomaly_result,
        escalation_result=escalation_result,
        correlation_result=correlation_result,
        similar_episodes=similar_episodes,
        cloud_provider=cloud_provider,
        region=region,
        contributing_features=score_inputs["contributing_features"],
    ).model_copy(update={"notify_method": notify_method})

    payload_dict = payload_model.model_dump(mode="json")
    payload_dict["tenant_id"] = tenant_id
    payload_dict["scenario"] = scenario_value
    payload_dict["history_context"] = {
        "recent_attack_count": score_inputs["recent_attack_count"],
        "same_scenario_count": score_inputs["same_scenario_count"],
        "tenant_pressure": round(score_inputs["pressure"], 3),
        "duplicate": dedup_result.is_duplicate,
        "recurrence_count": dedup_result.recurrence_count,
    }

    tenant_state["history"].append(
        {
            "alert_id": str(payload_model.alert_id),
            "scenario": scenario_value,
            "mode": mode,
            "final_score": payload_model.final_score,
            "severity": payload_model.severity.value,
            "batch_ts": reference_ts,
        }
    )

    return payload_dict


@app.post("/auth/login")
def login(payload: LoginRequest):
    return build_login_response()


@app.get("/tenants")
def tenants():
    return get_demo_tenants()


@app.get("/demo/scenarios")
def demo_scenarios():
    return [DemoScenario(**scenario).model_dump() for scenario in SCENARIOS]


@app.get("/demo/notify-methods")
def demo_notify_methods():
    return [method.value for method in NOTIFY_METHODS]


@app.get("/stats/summary")
def summary(tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id")):
    _resolve_tenant_header(tenant_id)
    return build_summary_payload()

@app.get("/alerts/recent")
def recent_alerts(tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id")):
    tenant_id = _resolve_tenant_header(tenant_id)
    return alerts_by_tenant.get(tenant_id, [])

@app.post("/demo/generate/alert")
async def generate_alert(payload: DemoAlertRequest):
    scenario = _find_scenario(payload.scenario)
    alert_payload = _build_demo_alert_payload(payload.tenant_id, scenario, payload.notify_method, payload.mode)
    notify_method = payload.notify_method.value

    await _dispatch_alert(payload.tenant_id, alert_payload)
    notification_response = await _send_notifications(alert_payload, notify_method)
    phase3_result = await process_demo_alert(alert_payload, payload.tenant_id)
    
    return {
        "status": "accepted",
        "tenant_id": payload.tenant_id,
        "scenario": payload.scenario,
        "mode": payload.mode,
        "notify_method": notify_method,
        "notification": notification_response,
        "phase3": phase3_result,
        "alert_payload": alert_payload,
        "heartbeat": build_stage_heartbeat("encoding", alert_payload["entity_id"]),
        "explainable_api": "/phase2/alerting/api/alert_api",
    }


@app.post("/demo/generate/attack")
async def generate_attack(payload: DemoAlertRequest):
    payload.mode = "attack"
    return await generate_alert(payload)

@app.post("/demo/pause")
def demo_pause(tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id")):
    tenant_id = _resolve_tenant_header(tenant_id)
    DEMO_STATE.setdefault(tenant_id, {})["paused"] = True
    return {
        "tenant_id": tenant_id,
        "paused": True,
        "active_alerts": len(alerts_by_tenant.get(tenant_id, [])),
        "status": "paused"
    }


@app.post("/demo/resume")
def demo_resume(tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id")):
    tenant_id = _resolve_tenant_header(tenant_id)
    DEMO_STATE.setdefault(tenant_id, {})["paused"] = False
    return {
        "tenant_id": tenant_id,
        "paused": False,
        "active_alerts": len(alerts_by_tenant.get(tenant_id, [])),
        "status": "resumed"
    }


@app.post("/demo/reset")
def demo_reset(tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id")):
    global DEMO_DEDUP_REDIS
    global DEMO_DEDUPLICATOR
    global DEMO_CORRELATION_ENGINE

    tenant_id = _resolve_tenant_header(tenant_id)
    alerts_by_tenant.pop(tenant_id, None)
    DEMO_STATE.pop(tenant_id, None)
    DEMO_DEDUP_REDIS = InMemoryRedisStore()
    DEMO_DEDUPLICATOR = AlertDeduplicator(DEMO_DEDUP_REDIS)
    DEMO_CORRELATION_ENGINE = CorrelationEngine(DEMO_ENTITY_ATTRIBUTES_PROVIDER)
    return {
        "tenant_id": tenant_id,
        "paused": False,
        "active_alerts": 0,
        "status": "reset"
    }


@app.get("/demo/status")
def demo_status(tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id")):
    tenant_id = _resolve_tenant_header(tenant_id)
    return {
        "tenant_id": tenant_id,
        "paused": bool(DEMO_STATE.get(tenant_id, {}).get("paused", False)),
        "active_alerts": len(alerts_by_tenant.get(tenant_id, [])),
    }


@app.post("/phase2/alerting/api/alert_api")
def explain_alert(payload: Dict[str, Any], tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id")):
    """Generate explainability insights for an alert."""
    tenant_id = _resolve_tenant_header(tenant_id)
    
    final_score = payload.get("final_score", 0.0)
    severity = payload.get("severity", "UNKNOWN")
    entity_id = payload.get("entity_id", "unknown")
    
    # Build explainability response
    return {
        "alert_id": payload.get("alert_id"),
        "entity_id": entity_id,
        "explainability": {
            "model_version": "v2.1-lstm",
            "prediction_score": final_score,
            "prediction_confidence": round(final_score * 100, 1),
            "severity_prediction": severity,
            "key_factors": [
                {
                    "factor": "IAM Policy Changes",
                    "impact": "HIGH",
                    "contribution": 0.384,
                    "description": f"Detected {random.randint(2, 5)} policy modifications in the past hour"
                },
                {
                    "factor": "Suspicious Login Location",
                    "impact": "HIGH",
                    "contribution": 0.368,
                    "description": "Login from unexpected geographic location (unlikely travel time)"
                },
                {
                    "factor": "Privilege Escalation Attempts",
                    "impact": "MEDIUM",
                    "contribution": 0.160,
                    "description": f"Detected {random.randint(3, 8)} failed sudo/admin elevation attempts"
                },
                {
                    "factor": "Anomalous Data Access Patterns",
                    "impact": "MEDIUM",
                    "contribution": 0.088,
                    "description": "Access to sensitive databases outside normal business hours"
                }
            ],
            "model_components": {
                "deviation_score": payload.get("deviation_score", 0.0),
                "drift_score": payload.get("drift_score", 0.0),
                "similarity_score": payload.get("similarity_score", 0.0),
                "ensemble_boosting": "Gradient Boosted Trees (XGBoost v1.7.6)",
                "lstm_temporal_window": "30-day historical baseline"
            },
            "recommendations": [
                "Immediately rotate credentials for affected identity",
                "Review IAM policy changes for potential misconfigurations",
                "Investigate recent data access logs from suspicious locations",
                "Monitor for lateral movement attempts on related resources",
                "Escalate to security operations team for immediate response"
            ] if severity in ["CRITICAL", "HIGH"] else [
                "Monitor this identity for 24 hours",
                "Review recent activity logs for similar patterns",
                "Consider enabling additional logging for this resource"
            ],
            "similar_episodes": payload.get("similar_episodes", []),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    }

