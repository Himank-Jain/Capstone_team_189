"""
AwsLiveIngestor
----------------
Real, read-only AWS connector using CloudTrail (activity/operations events)
and CloudWatch (resource metric readings). Requires: pip install boto3

IAM: attach config/cloud/aws_readonly_policy.json to a
dedicated IAM user/role. This connector never calls a mutating API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from live_ingestion.connectors.base_live_ingestor import BaseLiveIngestor, LiveIngestorConfigData
from live_ingestion.mappers.vocab_reconciler import VocabReconciler
from shared.types import RawRecord

logger = logging.getLogger(__name__)

# eventSource -> (entity_type, namespace) — extend as needed; unmapped sources fall to UNK
EVENT_SOURCE_MAP = {
    "ec2.amazonaws.com": ("EC2Instance", "compute"),
    "ebs.amazonaws.com": ("EBSVolume", "storage"),
    "s3.amazonaws.com": ("S3Bucket", "storage"),
    "iam.amazonaws.com": ("IAMResource", "identity"),
    "rds.amazonaws.com": ("RDSInstance", "database"),
    "lambda.amazonaws.com": ("LambdaFunction", "compute"),
}


class AwsLiveIngestor(BaseLiveIngestor):
    def __init__(self, cfg: LiveIngestorConfigData, vocab_reconciler: Optional[VocabReconciler] = None):
        super().__init__(cfg)
        import boto3  # local import so this module can be imported without boto3 installed

        creds = cfg.credentials_cfg or {}
        session_kwargs = {}
        if creds.get("aws_access_key_id"):
            session_kwargs.update(
                aws_access_key_id=creds["aws_access_key_id"],
                aws_secret_access_key=creds["aws_secret_access_key"],
                region_name=creds.get("region_name", "us-east-1"),
            )
        self._session = boto3.Session(**session_kwargs) if session_kwargs else boto3.Session()
        self._cloudtrail = self._session.client("cloudtrail")
        self._cloudwatch = self._session.client("cloudwatch")
        self.vocab = vocab_reconciler

    # -- BaseLiveIngestor implementation -------------------------------------

    def health_check(self) -> bool:
        try:
            self._cloudtrail.describe_trails(includeShadowTrails=False)
            return True
        except Exception as exc:
            logger.error("aws_live_ingestor.health_check_failed error=%s", exc)
            return False

    def _fetch_raw_events(self, since_ts: datetime) -> list:
        events = []
        paginator = self._cloudtrail.get_paginator("lookup_events")
        for page in paginator.paginate(
            StartTime=since_ts,
            EndTime=datetime.now(timezone.utc),
            PaginationConfig={"MaxItems": self.cfg.max_events_per_poll},
        ):
            events.extend(page.get("Events", []))
        return events

    def _map_to_raw_record(self, raw_event: dict) -> Optional[RawRecord]:
        import json as _json

        event_detail = _json.loads(raw_event.get("CloudTrailEvent", "{}"))
        event_source = event_detail.get("eventSource", "")
        entity_type, namespace = EVENT_SOURCE_MAP.get(event_source, ("Unknown", "other"))

        entity_id = None
        resources = event_detail.get("resources") or []
        if resources:
            entity_id = resources[0].get("ARN")
        if not entity_id:
            entity_id = event_detail.get("userIdentity", {}).get("arn", "unknown-entity")

        op_id = event_detail.get("eventName", "UnknownOperation")
        region = event_detail.get("awsRegion", "unknown-region")
        timestamp_str = event_detail.get("eventTime")
        timestamp = (
            datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if timestamp_str
            else datetime.now(timezone.utc)
        )

        categorical_fields = {
            "cloud": "AWS",
            "entity_type": entity_type,
            "namespace": namespace,
            "metric_name": "api_call",  # pure-activity event; metric-sourced readings set this per-metric
        }

        if self.vocab is not None:
            resolved, any_oov = self.vocab.resolve_categorical_fields(categorical_fields)
            categorical_fields = resolved
            if any_oov:
                self._oov_count += 1

        return RawRecord(
            entity_id=entity_id,
            timestamp=timestamp,
            op_id=op_id,
            region=region,
            cloud_provider="AWS",
            numeric_features=[1.0],  # activity-event presence signal; see 16.3 for metric-reading variant
            categorical_fields=categorical_fields,
        )

    # -- optional: resource-metric variant (CloudWatch), used for CPU/memory-style anomalies -----

    def fetch_resource_metric_records(
        self, entity_id: str, metric_name: str, namespace: str, since_ts: datetime
    ) -> List[RawRecord]:
        """Separate path for numeric telemetry (e.g. CPUUtilization) rather than pure activity
        events — call this alongside poll() for entities you want metric-level behavioral coverage on,
        not just API-call activity. Kept separate because CloudWatch GetMetricData is billed per call;
        only fetch for entities actively being profiled."""
        response = self._cloudwatch.get_metric_data(
            MetricDataQueries=[
                {
                    "Id": "m1",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": namespace,
                            "MetricName": metric_name,
                            "Dimensions": [{"Name": "InstanceId", "Value": entity_id}],
                        },
                        "Period": 300,
                        "Stat": "Average",
                    },
                }
            ],
            StartTime=since_ts,
            EndTime=datetime.now(timezone.utc),
        )
        records = []
        for result in response.get("MetricDataResults", []):
            for ts, value in zip(result.get("Timestamps", []), result.get("Values", [])):
                categorical_fields = {
                    "cloud": "AWS", "entity_type": "EC2Instance", "namespace": "compute",
                    "metric_name": metric_name,
                }
                if self.vocab is not None:
                    categorical_fields, _ = self.vocab.resolve_categorical_fields(categorical_fields)
                records.append(
                    RawRecord(
                        entity_id=entity_id, timestamp=ts, op_id="MetricReading",
                        region=self._session.region_name or "us-east-1", cloud_provider="AWS",
                        numeric_features=[float(value)], categorical_fields=categorical_fields,
                    )
                )
        return records
