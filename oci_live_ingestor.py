"""
OciLiveIngestor
-----------------
Real, read-only OCI connector using the Audit service.
Requires: pip install oci

IAM: create a Group + Policy limited to read audit-events + inspect all-resources
in the tenancy — see live_ingestion/iam_policies/oci_policy.txt. Auth via API
signing key configured in ~/.oci/config (or an in-memory config dict).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from shared.types import RawRecord
from live_ingestion.connectors.base_live_ingestor import BaseLiveIngestor, LiveIngestorConfigData
from live_ingestion.mappers.vocab_reconciler import VocabReconciler

logger = logging.getLogger(__name__)

RESOURCE_NAME_PREFIX_MAP = {
    "instance": ("ComputeInstance", "compute"),
    "volume": ("BlockVolume", "storage"),
    "bucket": ("ObjectStorageBucket", "storage"),
    "policy": ("IAMResource", "identity"),
}


class OciLiveIngestor(BaseLiveIngestor):
    def __init__(self, cfg: LiveIngestorConfigData, vocab_reconciler: Optional[VocabReconciler] = None):
        super().__init__(cfg)
        import oci

        creds = cfg.credentials_cfg or {}
        oci_config = creds.get("oci_config") or oci.config.from_file()
        self._compartment_id = creds["oci_compartment_id"]
        self._client = oci.audit.AuditClient(oci_config)
        self.vocab = vocab_reconciler

    def health_check(self) -> bool:
        try:
            from datetime import timedelta
            now = datetime.now(timezone.utc)
            self._client.list_events(
                compartment_id=self._compartment_id,
                start_time=now - timedelta(minutes=1),
                end_time=now,
            )
            return True
        except Exception as exc:
            logger.error("oci_live_ingestor.health_check_failed error=%s", exc)
            return False

    def _fetch_raw_events(self, since_ts: datetime) -> list:
        response = self._client.list_events(
            compartment_id=self._compartment_id,
            start_time=since_ts,
            end_time=datetime.now(timezone.utc),
        )
        return response.data[: self.cfg.max_events_per_poll]

    def _map_to_raw_record(self, raw_event) -> Optional[RawRecord]:
        data = getattr(raw_event, "data", None)
        resource_name = getattr(data, "resource_name", "") if data else ""
        prefix = resource_name.split("_")[0].lower() if resource_name else "unknown"
        entity_type, namespace = RESOURCE_NAME_PREFIX_MAP.get(prefix, ("Unknown", "other"))

        entity_id = getattr(data, "resource_id", None) or resource_name or "unknown-entity"
        op_id = getattr(data, "event_name", "UnknownOperation")
        region = getattr(raw_event, "source", "unknown-region")
        timestamp = getattr(raw_event, "event_time", None) or datetime.now(timezone.utc)

        categorical_fields = {
            "cloud": "OCI", "entity_type": entity_type, "namespace": namespace,
            "metric_name": "api_call",
        }
        if self.vocab is not None:
            categorical_fields, any_oov = self.vocab.resolve_categorical_fields(categorical_fields)
            if any_oov:
                self._oov_count += 1

        return RawRecord(
            entity_id=entity_id, timestamp=timestamp, op_id=op_id, region=region,
            cloud_provider="OCI", numeric_features=[1.0], categorical_fields=categorical_fields,
        )
