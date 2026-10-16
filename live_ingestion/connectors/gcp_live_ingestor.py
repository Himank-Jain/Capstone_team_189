"""
GcpLiveIngestor
-----------------
Real, read-only GCP connector using Cloud Logging (Cloud Audit Logs).
Requires: pip install google-cloud-logging

IAM: bind the Service Account to roles/logging.viewer + roles/monitoring.viewer
on the target project only — see config/cloud/gcp_custom_role.yaml.
Auth via GOOGLE_APPLICATION_CREDENTIALS pointing at the SA JSON key.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from live_ingestion.connectors.base_live_ingestor import BaseLiveIngestor, LiveIngestorConfigData
from live_ingestion.mappers.vocab_reconciler import VocabReconciler
from shared.types import RawRecord

logger = logging.getLogger(__name__)

RESOURCE_TYPE_MAP = {
    "gce_instance": ("ComputeInstance", "compute"),
    "gcs_bucket": ("StorageBucket", "storage"),
    "cloudsql_database": ("CloudSQLInstance", "database"),
    "iam_role": ("IAMResource", "identity"),
}


class GcpLiveIngestor(BaseLiveIngestor):
    def __init__(self, cfg: LiveIngestorConfigData, vocab_reconciler: Optional[VocabReconciler] = None):
        super().__init__(cfg)
        from google.cloud import logging as gcp_logging

        creds = cfg.credentials_cfg or {}
        self._project_id = creds["gcp_project_id"]
        self._client = gcp_logging.Client(project=self._project_id)
        self.vocab = vocab_reconciler

    def health_check(self) -> bool:
        try:
            list(self._client.list_entries(page_size=1))
            return True
        except Exception as exc:
            logger.error("gcp_live_ingestor.health_check_failed error=%s", exc)
            return False

    def _fetch_raw_events(self, since_ts: datetime) -> list:
        filter_str = (
            f'logName="projects/{self._project_id}/logs/cloudaudit.googleapis.com%2Factivity" '
            f'AND timestamp >= "{since_ts.isoformat()}"'
        )
        entries = self._client.list_entries(filter_=filter_str, page_size=self.cfg.max_events_per_poll)
        return list(entries)

    def _map_to_raw_record(self, raw_event) -> Optional[RawRecord]:
        payload = getattr(raw_event, "payload", {}) or {}
        resource = getattr(raw_event, "resource", None)
        resource_type = getattr(resource, "type", "unknown") if resource else "unknown"
        resource_labels = getattr(resource, "labels", {}) if resource else {}

        entity_type, namespace = RESOURCE_TYPE_MAP.get(resource_type, ("Unknown", "other"))
        entity_id = payload.get("resourceName", resource_labels.get("instance_id", "unknown-entity"))
        op_id = payload.get("methodName", "UnknownOperation")
        region = resource_labels.get("location") or resource_labels.get("zone", "unknown-region")
        timestamp = getattr(raw_event, "timestamp", None) or datetime.now(timezone.utc)

        categorical_fields = {
            "cloud": "GCP", "entity_type": entity_type, "namespace": namespace,
            "metric_name": "api_call",
        }
        if self.vocab is not None:
            categorical_fields, any_oov = self.vocab.resolve_categorical_fields(categorical_fields)
            if any_oov:
                self._oov_count += 1

        return RawRecord(
            entity_id=entity_id, timestamp=timestamp, op_id=op_id, region=region,
            cloud_provider="GCP", numeric_features=[1.0], categorical_fields=categorical_fields,
        )
