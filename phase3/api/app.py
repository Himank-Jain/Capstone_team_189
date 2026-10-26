import random
from contextlib import asynccontextmanager
import copy
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import yaml
from sqlalchemy import func
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from phase2.alerting.alert_deduplicator import AlertDeduplicator
from phase2.alerting.api.payload_builder import build_alert_payload
from phase2.alerting.correlation_engine import BaseEntityAttributesProvider, CorrelationEngine
from phase2.alerting.escalation_engine import (
    EntityMetadata,
    EscalationEngine,
    StaticEntityMetadataProvider,
)
from phase2.detection.anomaly_scorer import AnomalyScorer
from phase2.detection.cosine_deviation_scorer import CosineDeviationScorer
from phase2.detection.mmd_drift_monitor import mmd_rbf
from phase2.encoding.record_encoder import RecordEncoder
from phase2.encoding.reference_encoder_service import load_inference_encoder_from_manifest
from demo_generator.generator import DemoGenerator, metric_family_matches
from phase3.api.routers import _support, router as phase3_router
from phase3.api.routers.auth import bootstrap_admin_from_env
from phase3.api.routers._support import require_tenant_membership
from phase3.db.models import IncidentRow, RcaCaseRow, TenantRow
from phase3.lifecycle.incident_resolution_service import IncidentResolutionService
from phase3.api.routers.rca import process_demo_alert
from phase3.shared.types import IncidentStatus, ResolutionType
from shared.types import (
    CurrentEmbedding,
    EntityAttributesData,
    EntityProfile,
    EpisodeMatch,
    NotifyMethod,
    RawRecord,
    ScoringInput,
)

from .analytics import build_summary_payload
from .alert_notifications import send_alert_notification
from .ws_common import broadcast_alert
from .ws_heartbeat import build_stage_heartbeat
from .ws_router import router as ws_router

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Creates/promotes the CAPSTONE_ADMIN_EMAIL account when set; no-op otherwise.
    bootstrap_admin_from_env()
    yield


app = FastAPI(title="CAPSTONE-189 Demo API", lifespan=_lifespan)

alerts_by_tenant: Dict[str, List[Dict[str, Any]]] = {}

DEMO_STATE: Dict[str, Dict[str, Any]] = {}
DEMO_GENERATOR = DemoGenerator()

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
    "acme": {
        "entity_id": "vol-acme",
        "cloud_provider": "AWS",
        "region": "us-west-2",
        "entity_criticality": "critical",
        "timezone": "America/Los_Angeles",
    },
}
DEMO_PROVIDER_REGIONS = {
    "AWS": "us-east-1",
    "Azure": "eastus",
    "GCP": "us-central1",
    "OCI": "us-phoenix-1",
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

    def delete_by_prefix(self, prefix: str) -> None:
        for key in [key for key in self._values if key.startswith(prefix)]:
            self._values.pop(key, None)
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
_LIFECYCLE_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
_LIFECYCLE_CONFIG = (yaml.safe_load(_LIFECYCLE_CONFIG_PATH.read_text(encoding="utf-8")) or {}).get(
    "incident_lifecycle", {}
)


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
    """Deliver the alert through the operator's chosen channel and report the outcome."""
    tenant_id = (
        str(payload.get("tenant_id") or payload.get("tenant", "default")).strip().lower()
        or "default"
    )
    return await send_alert_notification(notify_method, payload, tenant_id)


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


class DemoScenario(BaseModel):
    value: str
    label: str
    description: str
    category: str
    default_notify_method: str
    severity: str
    providers: List[str]
    entity_types: List[str]
    signature: List[Dict[str, Any]]
    minimum_severity: str


class DemoAlertRequest(BaseModel):
    tenant_id: str
    scenario: str
    notify_method: NotifyMethod = NotifyMethod.PAGE
    mode: str = "attack"
    cloud_provider: Optional[str] = None
    intensity: str = "medium"
    seed: Optional[int] = None


SCENARIOS: List[Dict[str, Any]] = [
    {
        **scenario,
        "default_notify_method": NotifyMethod.PAGE.value,
        "severity": scenario["minimum_severity"],
    }
    for scenario in DEMO_GENERATOR.list_scenarios()
]

NOTIFY_METHODS: List[NotifyMethod] = [NotifyMethod.PAGE, NotifyMethod.SLACK, NotifyMethod.EMAIL]


def _find_scenario(scenario_value: str) -> Dict[str, Any]:
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
        item
        for item in tenant_state["history"]
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
    current_score: float,
) -> List[EpisodeMatch]:
    similar_episodes: List[EpisodeMatch] = []

    for index, prior_event in enumerate(reversed(tenant_history[-3:])):
        score_gap = abs(current_score - prior_event["final_score"])
        similarity_score = _clip01(0.92 - (score_gap * 0.70) - (index * 0.05))
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
_BASELINE_LIFECYCLE: Dict[tuple[str, str], Dict[str, Any]] = {}
_DRIFT_SCORE_CACHE: Dict[tuple[str, str], float] = {}


class _DemoDedupResetPort:
    def reset_entity(self, entity_id: str) -> None:
        DEMO_DEDUPLICATOR.reset_entity(entity_id)


class _DemoCorrelationPort:
    def remove_entity(self, tenant_id: str, entity_id: str) -> None:
        DEMO_CORRELATION_ENGINE.forget_entity(entity_id)


class _DemoEscalationMemory:
    def clear_group(self, incident_group_id: str) -> None:
        DEMO_ESCALATION_ENGINE.clear_suppression_memory(incident_group_id)


class _DemoDriftCachePort:
    def invalidate(self, tenant_id: str, entity_id: str) -> None:
        _DRIFT_SCORE_CACHE.pop((tenant_id, entity_id), None)


class _DemoEntityRecoveryPort:
    def freeze(self, tenant_id: str, entity_id: str) -> None:
        key = (tenant_id, entity_id)
        state = _BASELINE_LIFECYCLE.setdefault(
            key,
            {
                "pre_profile": copy.deepcopy(_ML_ENTITY_PROFILES.get(entity_id)),
                "frozen_embeddings": [],
                "adaptation_batches_remaining": 0,
            },
        )
        state["frozen"] = True

    def resolve(
        self, tenant_id: str, entity_id: str, resolution_type: ResolutionType
    ) -> None:
        key = (tenant_id, entity_id)
        state = _BASELINE_LIFECYCLE.get(key)
        if state is None:
            return
        prior_profile = state.get("pre_profile")
        if resolution_type in {ResolutionType.FIXED, ResolutionType.AUTO_RECOVERED}:
            if prior_profile is not None:
                _ML_ENTITY_PROFILES[entity_id] = copy.deepcopy(prior_profile)
            state["adaptation_batches_remaining"] = 0
        elif resolution_type in {ResolutionType.FALSE_POSITIVE, ResolutionType.EXPECTED_CHANGE}:
            profile = _ML_ENTITY_PROFILES.get(entity_id)
            embeddings = state.get("frozen_embeddings", [])
            baseline_config = _LIFECYCLE_CONFIG.get("baseline", {})
            adaptation_alpha = float(baseline_config.get("adaptation_alpha", 0.35))
            adaptation_window = int(baseline_config.get("adaptation_window", 20))
            selected = embeddings[-adaptation_window:]
            if profile is not None and selected:
                centroid = profile.centroid_emb.copy()
                for embedding in selected:
                    centroid = (1 - adaptation_alpha) * centroid + adaptation_alpha * embedding
                    norm = float(np.linalg.norm(centroid))
                    if norm:
                        centroid /= norm
                profile.centroid_emb = centroid.astype(np.float32)
                profile.history_embs = (profile.history_embs + selected)[-30:]
            state["adaptation_batches_remaining"] = int(
                baseline_config.get("adaptation_batches", 5)
            )
        state["frozen"] = False
        state["frozen_embeddings"] = []


class _DemoNotificationPort:
    async def send_resolved(self, tenant_id: str, incident_id: str, entity_id: str) -> None:
        await _support.send_resolved_notification(tenant_id, incident_id, entity_id)


_support.configure_incident_resolution_service(
    IncidentResolutionService(
        dedup=_DemoDedupResetPort(),
        correlation=_DemoCorrelationPort(),
        entity_recovery=_DemoEntityRecoveryPort(),
        drift_cache=_DemoDriftCachePort(),
        notification_dispatcher=_DemoNotificationPort(),
        audit_logger=_support.DatabaseAuditPort(),
        escalation_memory=_DemoEscalationMemory(),
    )
)


def _get_ml_components():
    global _ML_INFERENCE_ENCODER, _ML_FEATURE_META, _ML_RECORD_ENCODER
    if _ML_INFERENCE_ENCODER is None:
        try:
            manifest_path = (
                Path(__file__).parent.parent.parent / "model_registry" / "artifacts_manifest.json"
            )
            _ML_INFERENCE_ENCODER, _ML_FEATURE_META = load_inference_encoder_from_manifest(
                str(manifest_path)
            )
            _ML_RECORD_ENCODER = RecordEncoder(_ML_FEATURE_META, seq_len=32)
            print("[ML Engine] Loaded T-STCC PyTorch encoder model from registry.")
        except Exception as exc:
            print(
                f"[ML Engine] Warning: Could not load PyTorch model ({exc}). "
                "Using baseline fallback."
            )
    return _ML_INFERENCE_ENCODER, _ML_RECORD_ENCODER


def _generate_telemetry_records(
    entity_id: str,
    cloud: str,
    scenario_value: str,
    mode: str,
    now: datetime,
    intensity: str = "medium",
    seed: Optional[int] = None,
) -> List[RawRecord]:
    effective_scenario = "benign_baseline" if mode == "normal" else scenario_value
    return DEMO_GENERATOR.generate_events(
        effective_scenario,
        cloud,
        intensity,
        entity_id=entity_id,
        seed=seed,
        start_time=now - timedelta(minutes=32),
    )


def _scenario_scoring_profile(scenario_value: str, intensity: str) -> Dict[str, Any]:
    scenario = DEMO_GENERATOR.get_scenario(scenario_value)
    intensity_multiplier = scenario.intensity_presets[intensity]
    supported_signatures = [
        signature
        for signature in scenario.signature
        if metric_family_matches(signature.metric_family, DEMO_GENERATOR.metric_vocabulary)
    ]
    impact = max(
        (
            1.0 + (signature.magnitude - 1.0) * intensity_multiplier
            for signature in supported_signatures
        ),
        default=1.0,
    )
    signal = _clip01((impact - 1.0) / 5.0)
    return {
        "deviation_base": _clip01(0.08 + signal * 0.82),
        "drift_base": _clip01(0.10 + signal * 0.72),
        "similarity_base": _clip01(0.94 - signal * 0.82),
        "op_id": "synthetic-metric-pattern",
        "contributing_features": [
            f"metric_family:{signature.metric_family}"
            for signature in supported_signatures
        ],
        "metric_directions": {
            signature.metric_family: signature.direction
            for signature in supported_signatures
        },
    }


def _get_or_create_entity_profile(entity_id: str, cloud: str, now: datetime) -> EntityProfile:
    if entity_id in _ML_ENTITY_PROFILES:
        return _ML_ENTITY_PROFILES[entity_id]

    inf_enc, rec_enc = _get_ml_components()
    if inf_enc and rec_enc:
        base_recs = _generate_telemetry_records(
            entity_id, cloud, "benign_baseline", "normal", now - timedelta(hours=2)
        )
        enc_dict = rec_enc.encode_entity_records(base_recs)
        base_emb = (
            inf_enc.encode(
                enc_dict["numeric"].unsqueeze(0),
                enc_dict["categorical"].unsqueeze(0),
                enc_dict["timestamps"].unsqueeze(0),
            )
            .cpu()
            .numpy()[0]
        )

        history_embs = [
            (base_emb + np.random.normal(0, 0.005, size=128)).astype(np.float32) for _ in range(15)
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
    intensity: str = "medium",
    seed: Optional[int] = None,
    tenant_id: str = "demo",
) -> Dict[str, Any]:
    _prune_demo_history(tenant_state, reference_ts)
    tenant_history = tenant_state["history"]

    inf_enc, rec_enc = _get_ml_components()
    entity_prof = _get_or_create_entity_profile(entity_id, cloud_provider, reference_ts)
    baseline_before = copy.deepcopy(entity_prof)
    live_emb: Optional[np.ndarray] = None

    recs = _generate_telemetry_records(
        entity_id, cloud_provider, scenario_value, mode, reference_ts, intensity, seed
    )
    if inf_enc and rec_enc and recs:
        enc_dict = rec_enc.encode_entity_records(recs)

        # Pass raw tensors into loaded PyTorch TSTCC Encoder
        live_emb = (
            inf_enc.encode(
                enc_dict["numeric"].unsqueeze(0),
                enc_dict["categorical"].unsqueeze(0),
                enc_dict["timestamps"].unsqueeze(0),
            )
            .cpu()
            .numpy()[0]
        )

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
        raw_similarity = _clip01(1.0 - raw_deviation)

        # 2. MMD distribution drift
        recent_embs = np.array([live_emb] * 5 + entity_prof.history_embs[-5:])
        hist_embs = np.array(entity_prof.history_embs)
        mmd_val = float(mmd_rbf(recent_embs, hist_embs, sigma=1.0))
        raw_drift = min(1.0, max(0.0, mmd_val * 4.5))

        lifecycle = _BASELINE_LIFECYCLE.get((tenant_id, entity_id), {})
        if lifecycle.get("frozen"):
            lifecycle.setdefault("frozen_embeddings", []).append(live_emb.copy())
            max_window = int(_LIFECYCLE_CONFIG.get("baseline", {}).get("adaptation_window", 20))
            lifecycle["frozen_embeddings"] = lifecycle["frozen_embeddings"][-max_window:]
        else:
            baseline_config = _LIFECYCLE_CONFIG.get("baseline", {})
            adaptation_batches = int(lifecycle.get("adaptation_batches_remaining", 0))
            alpha = (
                float(baseline_config.get("adaptation_alpha", 0.35))
                if adaptation_batches > 0
                else 0.1
            )
            entity_prof.history_embs.append(live_emb)
            if len(entity_prof.history_embs) > 30:
                entity_prof.history_embs.pop(0)
            entity_prof.centroid_emb = (1 - alpha) * entity_prof.centroid_emb + alpha * live_emb
            entity_prof.centroid_emb /= float(np.linalg.norm(entity_prof.centroid_emb))
            entity_prof.last_update_ts = reference_ts
            if adaptation_batches > 0:
                lifecycle["adaptation_batches_remaining"] = adaptation_batches - 1

        deviation_score = _clip01(max(raw_deviation, profile_info["deviation_base"] * 0.8))
        drift_score = _clip01(max(raw_drift, profile_info["drift_base"] * 0.8))
        similarity_score = _clip01(min(raw_similarity, profile_info["similarity_base"] + 0.15))
    else:
        deviation_score = profile_info["deviation_base"]
        drift_score = profile_info["drift_base"]
        similarity_score = profile_info["similarity_base"]

    return {
        "deviation_score": deviation_score,
        "drift_score": drift_score,
        "similarity_score": similarity_score,
        "contributing_features": profile_info["contributing_features"],
        "case_evidence": {
            "entity_types": sorted({record.entity_type for record in recs}),
            "namespaces": sorted({record.namespace for record in recs if record.namespace}),
            "metric_directions": profile_info["metric_directions"],
        },
        "recent_alert_count": len(tenant_history),
        "generated_metric_count": len(recs),
        "_baseline_before": baseline_before,
        "_live_embedding": live_emb,
    }


def _freeze_demo_baseline(
    tenant_id: str,
    entity_id: str,
    baseline_before: Optional[EntityProfile],
    live_embedding: Optional[np.ndarray],
) -> None:
    key = (tenant_id, entity_id)
    existing = _BASELINE_LIFECYCLE.get(key)
    if existing and existing.get("frozen"):
        return
    _BASELINE_LIFECYCLE[key] = {
        "frozen": True,
        "pre_profile": copy.deepcopy(
            baseline_before or _ML_ENTITY_PROFILES.get(entity_id)
        ),
        "frozen_embeddings": [live_embedding.copy()] if live_embedding is not None else [],
        "adaptation_batches_remaining": 0,
    }
    if baseline_before is not None:
        _ML_ENTITY_PROFILES[entity_id] = copy.deepcopy(baseline_before)


def _recent_fixed_regression(
    tenant_id: str, entity_id: str, reference_ts: datetime
) -> Optional[str]:
    window_minutes = int(_LIFECYCLE_CONFIG.get("regression_window_minutes", 30))
    with _support.platform_session_factory.session_scope() as session:
        rows = (
            session.query(IncidentRow)
            .filter_by(
                tenant_id=tenant_id,
                entity_id=entity_id,
                resolution_type=ResolutionType.FIXED.value,
            )
            .filter(func.upper(IncidentRow.status) == IncidentStatus.RESOLVED.value)
            .order_by(IncidentRow.resolved_at.desc())
            .all()
        )
    for row in rows:
        if row.resolved_at is None:
            continue
        resolved_at = row.resolved_at
        if resolved_at.tzinfo is None:
            resolved_at = resolved_at.replace(tzinfo=timezone.utc)
        if timedelta(0) <= reference_ts - resolved_at <= timedelta(minutes=window_minutes):
            return row.incident_id
    return None


def _update_recovery_state(tenant_id: str, entity_id: str, final_score: float) -> None:
    recovery_config = _LIFECYCLE_CONFIG.get("recovery", {})
    low_threshold = float(recovery_config.get("low_score_threshold", 0.2))
    required_batches = int(recovery_config.get("consecutive_batches", 6))
    with _support.platform_session_factory.session_scope() as session:
        row = (
            session.query(IncidentRow)
            .filter(
                IncidentRow.tenant_id == tenant_id,
                IncidentRow.entity_id == entity_id,
                func.upper(IncidentRow.status).in_(
                    [IncidentStatus.OPEN.value, IncidentStatus.ACKNOWLEDGED.value]
                ),
            )
            .order_by(IncidentRow.first_seen_at.desc())
            .first()
        )
        if row is None:
            return
        details = dict(row.details or {})
        streak = int(details.get("recovery_streak", 0)) + 1 if final_score < low_threshold else 0
        details["recovery_streak"] = streak
        details["recovering"] = streak >= required_batches
        row.details = details


async def _auto_resolve_recovered_incident(tenant_id: str, incident_id: str) -> None:
    with _support.platform_session_factory.session_scope() as session:
        tenant = session.get(TenantRow, tenant_id)
        row = session.query(IncidentRow).filter_by(
            tenant_id=tenant_id, incident_id=incident_id
        ).one_or_none()
        settings = tenant.onboarding_state if tenant is not None else None
        tenant_settings = (settings or {}).get("settings", {})
        recovery_config = _LIFECYCLE_CONFIG.get("recovery", {})
        enabled = bool(
            tenant_settings.get(
                "auto_resolve_incidents", recovery_config.get("auto_resolve", False)
            )
        )
        if (
            not enabled
            or row is None
            or row.status.upper() not in {
                IncidentStatus.OPEN.value,
                IncidentStatus.ACKNOWLEDGED.value,
            }
            or not (row.details or {}).get("recovering", False)
        ):
            return
        now = datetime.now(timezone.utc)
        row.status = IncidentStatus.RESOLVED.value
        row.resolved_at = now
        row.resolved_by = "system"
        row.resolution_type = ResolutionType.AUTO_RECOVERED.value
        row.resolution_note = "Auto-resolved after sustained recovery below the LOW threshold."
        details = dict(row.details or {})
        details["recovering"] = False
        row.details = details
        entity_id = row.entity_id
        incident_group_id = details.get("incident_group_id")
    await _support.get_incident_resolution_service().resolve(
        tenant_id,
        incident_id,
        entity_id,
        "system",
        ResolutionType.AUTO_RECOVERED,
        incident_group_id,
    )


def _build_demo_alert_payload(
    tenant_id: str,
    scenario: Dict[str, Any],
    notify_method: NotifyMethod,
    mode: str,
    cloud_provider: Optional[str] = None,
    intensity: str = "medium",
    seed: Optional[int] = None,
) -> Dict[str, object]:
    reference_ts = _now_utc()
    tenant_profile = DEMO_TENANT_PROFILES.get(tenant_id, DEMO_TENANT_PROFILES["amazon"])
    scenario_value = scenario["value"]
    cloud_provider = cloud_provider or tenant_profile["cloud_provider"]
    scenario_spec = DEMO_GENERATOR.get_scenario(scenario_value)
    if cloud_provider not in scenario_spec.providers:
        raise HTTPException(status_code=400, detail="provider is not enabled for this scenario")
    if intensity not in scenario_spec.intensity_presets:
        raise HTTPException(status_code=400, detail="unsupported scenario intensity")
    entity_id = tenant_profile["entity_id"]
    region = (
        tenant_profile["region"]
        if cloud_provider == tenant_profile["cloud_provider"]
        else DEMO_PROVIDER_REGIONS[cloud_provider]
    )
    tenant_state = _get_tenant_state(tenant_id)
    effective_scenario = "benign_baseline" if mode == "normal" else scenario_value
    scenario_profile = _scenario_scoring_profile(effective_scenario, intensity)

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
        intensity=intensity,
        seed=seed,
        tenant_id=tenant_id,
    )

    anomaly_result = DEMO_ANOMALY_SCORER.score(
        ScoringInput(
            entity_id=entity_id,
            deviation_score=score_inputs["deviation_score"],
            drift_score=score_inputs["drift_score"],
            similarity_score=score_inputs["similarity_score"],
            batch_ts=reference_ts,
            component_scores={
                "recent_alert_count": float(score_inputs["recent_alert_count"]),
                "generated_metric_count": float(score_inputs["generated_metric_count"]),
            },
        )
    )

    dedup_result = DEMO_DEDUPLICATOR.check(anomaly_result)
    if not dedup_result.is_duplicate:
        _freeze_demo_baseline(
            tenant_id,
            entity_id,
            score_inputs.get("_baseline_before"),
            score_inputs.get("_live_embedding"),
        )
    correlation_result = DEMO_CORRELATION_ENGINE.process(
        entity_id=entity_id,
        canonical_incident_id=dedup_result.canonical_incident_id,
        alert_ts=reference_ts,
    )
    regression_of = (
        _recent_fixed_regression(tenant_id, entity_id, reference_ts)
        if not dedup_result.is_duplicate
        else None
    )
    if regression_of:
        DEMO_ESCALATION_ENGINE.clear_suppression_memory(correlation_result.incident_group_id)
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
    ).model_copy(
        update={
            "alert_id": uuid.UUID(dedup_result.canonical_incident_id),
            "notify_method": notify_method,
        }
    )

    payload_dict = payload_model.model_dump(mode="json")
    payload_dict["tenant_id"] = tenant_id
    payload_dict["incident_group_id"] = correlation_result.incident_group_id
    payload_dict["regression_of"] = regression_of
    payload_dict["history_context"] = {
        "recent_alert_count": score_inputs["recent_alert_count"],
        "generated_metric_count": score_inputs["generated_metric_count"],
        "duplicate": dedup_result.is_duplicate,
        "recurrence_count": dedup_result.recurrence_count,
    }
    payload_dict["case_evidence"] = score_inputs["case_evidence"]

    _update_recovery_state(tenant_id, entity_id, anomaly_result.final_score)
    tenant_state["history"].append(
        {
            "alert_id": str(payload_model.alert_id),
            "final_score": payload_model.final_score,
            "severity": payload_model.severity.value,
            "batch_ts": reference_ts,
        }
    )

    return payload_dict


@app.get("/demo/scenarios")
def demo_scenarios():
    return [DemoScenario(**scenario).model_dump() for scenario in SCENARIOS]


@app.get("/demo/notify-methods")
def demo_notify_methods():
    return [method.value for method in NOTIFY_METHODS]


@app.get("/stats/summary")
def summary(
    _authorized: bool = Depends(require_tenant_membership),
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
    resolved_tenant = _resolve_tenant_header(tenant_id)
    with _support.platform_session_factory.session_scope() as session:
        incidents = session.query(IncidentRow).filter_by(tenant_id=resolved_tenant).all()
    active = [
        row
        for row in incidents
        if row.status.upper() in {IncidentStatus.OPEN.value, IncidentStatus.ACKNOWLEDGED.value}
    ]
    resolved = [
        row
        for row in incidents
        if row.status.upper() == IncidentStatus.RESOLVED.value and row.resolved_at is not None
    ]
    today = datetime.now(timezone.utc).date()
    durations = []
    resolved_today = 0
    for row in resolved:
        resolved_at = row.resolved_at
        first_seen = row.first_seen_at
        if resolved_at.tzinfo is None:
            resolved_at = resolved_at.replace(tzinfo=timezone.utc)
        if first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=timezone.utc)
        if resolved_at.date() == today:
            resolved_today += 1
        durations.append((resolved_at - first_seen).total_seconds() / 60.0)
    payload = build_summary_payload()
    payload.update(
        {
            "active_alerts": len(active),
            "active_incidents": len(active),
            "critical_alerts": sum(row.severity.upper() == "CRITICAL" for row in active),
            "resolved_today": resolved_today,
            "mean_time_to_resolve_minutes": (
                round(sum(durations) / len(durations), 2) if durations else 0.0
            ),
        }
    )
    return payload


@app.get("/alerts/recent")
def recent_alerts(
    _authorized: bool = Depends(require_tenant_membership),
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
    tenant_id = _resolve_tenant_header(tenant_id)
    with _support.platform_session_factory.session_scope() as session:
        resolved_ids = {
            row.incident_id
            for row in session.query(IncidentRow).filter_by(tenant_id=tenant_id).all()
            if row.status.upper() == IncidentStatus.RESOLVED.value
        }
    return [
        alert
        for alert in alerts_by_tenant.get(tenant_id, [])
        if str(alert.get("alert_id")) not in resolved_ids
    ]


@app.post("/demo/generate/alert")
async def generate_alert(
    payload: DemoAlertRequest,
    _authorized: bool = Depends(require_tenant_membership),
    request_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
    return await _run_demo_alert(payload, request_tenant_id)


async def _run_demo_alert(
    payload: DemoAlertRequest,
    request_tenant_id: Optional[str],
) -> Dict[str, Any]:
    authenticated_tenant = _resolve_tenant_header(request_tenant_id)
    if payload.tenant_id != authenticated_tenant:
        raise HTTPException(status_code=403, detail="Requested tenant does not match membership")
    scenario = _find_scenario(payload.scenario)
    alert_payload = _build_demo_alert_payload(
        tenant_id=payload.tenant_id,
        scenario=scenario,
        notify_method=payload.notify_method,
        mode=payload.mode,
        cloud_provider=payload.cloud_provider,
        intensity=payload.intensity,
        seed=payload.seed,
    )
    case_evidence = alert_payload.pop("case_evidence", {})
    notify_method = payload.notify_method.value

    await _dispatch_alert(payload.tenant_id, alert_payload)
    notification_response = await _send_notifications(alert_payload, notify_method)
    phase3_result = await process_demo_alert(
        alert_payload, payload.tenant_id, case_evidence=case_evidence
    )
    if notify_method != NotifyMethod.PAGE.value:
        delivery = _support.record_channel_delivery(
            payload.tenant_id, str(alert_payload["alert_id"]), notification_response
        )
        phase3_result["notification_deliveries"].append(delivery)
    await _auto_resolve_recovered_incident(payload.tenant_id, str(alert_payload["alert_id"]))

    return {
        "status": "accepted",
        "tenant_id": payload.tenant_id,
        "notify_method": notify_method,
        "notification": notification_response,
        "phase3": phase3_result,
        "alert_payload": alert_payload,
        "heartbeat": build_stage_heartbeat("encoding", alert_payload["entity_id"]),
    }


@app.post("/demo/generate/attack")
async def generate_attack(
    payload: DemoAlertRequest,
    _authorized: bool = Depends(require_tenant_membership),
    request_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
    payload.mode = "attack"
    return await _run_demo_alert(payload, request_tenant_id)


@app.post("/demo/pause")
def demo_pause(
    _authorized: bool = Depends(require_tenant_membership),
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
    tenant_id = _resolve_tenant_header(tenant_id)
    DEMO_STATE.setdefault(tenant_id, {})["paused"] = True
    return {
        "tenant_id": tenant_id,
        "paused": True,
        "active_alerts": len(alerts_by_tenant.get(tenant_id, [])),
        "status": "paused",
    }


@app.post("/demo/resume")
def demo_resume(
    _authorized: bool = Depends(require_tenant_membership),
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
    tenant_id = _resolve_tenant_header(tenant_id)
    DEMO_STATE.setdefault(tenant_id, {})["paused"] = False
    return {
        "tenant_id": tenant_id,
        "paused": False,
        "active_alerts": len(alerts_by_tenant.get(tenant_id, [])),
        "status": "resumed",
    }


@app.post("/demo/reset")
def demo_reset(
    _authorized: bool = Depends(require_tenant_membership),
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
    tenant_id = _resolve_tenant_header(tenant_id)
    if tenant_id not in DEMO_TENANT_PROFILES:
        raise HTTPException(status_code=403, detail="Only synthetic demo tenants can be reset")
    with _support.platform_session_factory.session_scope() as session:
        tenant = session.get(TenantRow, tenant_id)
        if tenant is None or tenant.source_mode != "synthetic":
            raise HTTPException(status_code=403, detail="Only synthetic demo tenants can be reset")
        session.query(IncidentRow).filter_by(tenant_id=tenant_id).delete()
        session.query(RcaCaseRow).filter_by(tenant_id=tenant_id).delete()

    alerts_by_tenant.pop(tenant_id, None)
    DEMO_STATE.pop(tenant_id, None)
    for cache in (
        _support.rca_cases,
        _support.rca_explanations,
        _support.rca_recommendations,
    ):
        cache.pop(tenant_id, None)
    _support._delivery_recorder.clear_for_tenant(tenant_id)
    tenant_profile = DEMO_TENANT_PROFILES[tenant_id]
    entity_id = tenant_profile["entity_id"]
    DEMO_DEDUP_REDIS.delete_by_prefix(f"dedup:{entity_id}:")
    DEMO_CORRELATION_ENGINE.forget_entity(entity_id)
    _ML_ENTITY_PROFILES.pop(entity_id, None)
    _BASELINE_LIFECYCLE.pop((tenant_id, entity_id), None)
    _DRIFT_SCORE_CACHE.pop((tenant_id, entity_id), None)
    return {"tenant_id": tenant_id, "paused": False, "active_alerts": 0, "status": "reset"}


@app.get("/demo/status")
def demo_status(
    _authorized: bool = Depends(require_tenant_membership),
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
    tenant_id = _resolve_tenant_header(tenant_id)
    return {
        "tenant_id": tenant_id,
        "paused": bool(DEMO_STATE.get(tenant_id, {}).get("paused", False)),
        "active_alerts": len(alerts_by_tenant.get(tenant_id, [])),
    }


@app.post("/phase2/alerting/api/alert_api")
def explain_alert(
    payload: Dict[str, Any],
    _authorized: bool = Depends(require_tenant_membership),
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
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
                    "description": (
                        f"Detected {random.randint(2, 5)} policy modifications "
                        "in the past hour"
                    ),
                },
                {
                    "factor": "Suspicious Login Location",
                    "impact": "HIGH",
                    "contribution": 0.368,
                    "description": (
                        "Login from unexpected geographic location (unlikely "
                        "travel time)"
                    ),
                },
                {
                    "factor": "Privilege Escalation Attempts",
                    "impact": "MEDIUM",
                    "contribution": 0.160,
                    "description": (
                        f"Detected {random.randint(3, 8)} failed sudo/admin "
                        "elevation attempts"
                    ),
                },
                {
                    "factor": "Anomalous Data Access Patterns",
                    "impact": "MEDIUM",
                    "contribution": 0.088,
                    "description": "Access to sensitive databases outside normal business hours",
                },
            ],
            "model_components": {
                "deviation_score": payload.get("deviation_score", 0.0),
                "drift_score": payload.get("drift_score", 0.0),
                "similarity_score": payload.get("similarity_score", 0.0),
                "ensemble_boosting": "Gradient Boosted Trees (XGBoost v1.7.6)",
                "lstm_temporal_window": "30-day historical baseline",
            },
            "recommendations": (
                [
                    "Immediately rotate credentials for affected identity",
                    "Review IAM policy changes for potential misconfigurations",
                    "Investigate recent data access logs from suspicious locations",
                    "Monitor for lateral movement attempts on related resources",
                    "Escalate to security operations team for immediate response",
                ]
                if severity in ["CRITICAL", "HIGH"]
                else [
                    "Monitor this identity for 24 hours",
                    "Review recent activity logs for similar patterns",
                    "Consider enabling additional logging for this resource",
                ]
            ),
            "similar_episodes": payload.get("similar_episodes", []),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    }
