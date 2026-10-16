"""
AzureLiveIngestor
-------------------
Real, read-only Azure connector using Azure Monitor Activity Log.
Requires: pip install azure-identity azure-mgmt-monitor

IAM: assign the Service Principal 'Reader' + 'Monitoring Reader' roles,
scoped to a single subscription — see config/cloud/azure_role_definition.json.
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
    "Microsoft.Compute/virtualMachines": ("VirtualMachine", "compute"),
    "Microsoft.Storage/storageAccounts": ("StorageAccount", "storage"),
    "Microsoft.Network/networkSecurityGroups": ("NetworkSecurityGroup", "network"),
    "Microsoft.Authorization/roleAssignments": ("IAMResource", "identity"),
}


class AzureLiveIngestor(BaseLiveIngestor):
    def __init__(self, cfg: LiveIngestorConfigData, vocab_reconciler: Optional[VocabReconciler] = None):
        super().__init__(cfg)
        from azure.identity import ClientSecretCredential
        from azure.mgmt.monitor import MonitorManagementClient

        creds = cfg.credentials_cfg or {}
        credential = ClientSecretCredential(
            tenant_id=creds["azure_tenant_id"],
            client_id=creds["azure_client_id"],
            client_secret=creds["azure_client_secret"],
        )
        self._subscription_id = creds["azure_subscription_id"]
        self._client = MonitorManagementClient(credential, self._subscription_id)
        self.vocab = vocab_reconciler

    def health_check(self) -> bool:
        try:
            # cheap read-only call: list activity log entries for a 1-minute window
            next(iter(self._client.activity_logs.list(filter=self._time_filter(minutes=1))), None)
            return True
        except Exception as exc:
            logger.error("azure_live_ingestor.health_check_failed error=%s", exc)
            return False

    def _time_filter(self, since_ts: Optional[datetime] = None, minutes: Optional[int] = None) -> str:
        from datetime import timedelta
        start = since_ts or (datetime.now(timezone.utc) - timedelta(minutes=minutes or 5))
        end = datetime.now(timezone.utc)
        return (
            f"eventTimestamp ge '{start.isoformat()}' and eventTimestamp le '{end.isoformat()}'"
        )

    def _fetch_raw_events(self, since_ts: datetime) -> list:
        entries = self._client.activity_logs.list(filter=self._time_filter(since_ts=since_ts))
        return list(entries)[: self.cfg.max_events_per_poll]

    def _map_to_raw_record(self, raw_event) -> Optional[RawRecord]:
        resource_id = getattr(raw_event, "resource_id", None) or "unknown-entity"
        resource_type_str = getattr(raw_event, "resource_type", None)
        resource_type_value = getattr(resource_type_str, "value", "Unknown") if resource_type_str else "Unknown"
        entity_type, namespace = RESOURCE_TYPE_MAP.get(resource_type_value, ("Unknown", "other"))

        op_name = getattr(raw_event, "operation_name", None)
        op_id = getattr(op_name, "value", "UnknownOperation") if op_name else "UnknownOperation"

        timestamp = getattr(raw_event, "event_timestamp", None) or datetime.now(timezone.utc)
        region = getattr(raw_event, "resource_group_name", None) or "unknown-region"

        categorical_fields = {
            "cloud": "Azure", "entity_type": entity_type, "namespace": namespace,
            "metric_name": "api_call",
        }
        if self.vocab is not None:
            categorical_fields, any_oov = self.vocab.resolve_categorical_fields(categorical_fields)
            if any_oov:
                self._oov_count += 1

        return RawRecord(
            entity_id=resource_id, timestamp=timestamp, op_id=op_id, region=region,
            cloud_provider="Azure", numeric_features=[1.0], categorical_fields=categorical_fields,
        )
