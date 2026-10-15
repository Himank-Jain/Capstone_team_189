# Scenario metric vocabulary coverage

Generated from `model_registry/feature_meta.json` by `scripts/report_scenario_metric_coverage.py`.

| Metric family | Matching trained metric names | Status |
|---|---|---|
| `anonymous_requests` | — | **unmapped; no metric invented** |
| `api_calls` | `ActivitySucceededRuns`, `Invocations`, `Requests`, `ServiceApiHit`, `SuccessfulRequests`, `Transactions`, `storage.googleapis.com/api/request_count` | covered |
| `application_requests` | `AppConnections`, `Requests`, `ServiceApiHit`, `SuccessfulRequests`, `storage.googleapis.com/api/request_count` | covered |
| `audit_log_volume` | — | **unmapped; no metric invented** |
| `auth_failures` | `ActivityFailedRuns`, `Http4xx`, `PipelineFailedRuns` | covered |
| `configuration_changes` | — | **unmapped; no metric invented** |
| `cpu_utilization` | `CPU Credits Consumed`, `CPU Credits Remaining`, `CPUCreditBalance`, `CPUCreditUsage`, `CPUUtilization`, `CpuPercentage`, `CpuUsage`, `IntegrationRuntimeCpuPercentage`, `Percentage CPU`, `compute.googleapis.com/instance/cpu/utilization`, `cpu_percent`, `cpu_usage_idle`, `cpu_usage_iowait`, `cpu_usage_system`, `cpu_usage_user` | covered |
| `disk_write_ops` | `Composite Disk Write Operations/sec`, `Disk Write Operations/Sec`, `OS Disk Write Operations/Sec`, `VolumeWriteOps`, `compute.googleapis.com/instance/disk/write_ops_count` | covered |
| `east_west_connections` | `AppConnections`, `Inbound Flows`, `Inbound Flows Maximum Creation Rate`, `Outbound Flows`, `Outbound Flows Maximum Creation Rate` | covered |
| `estimated_cost` | — | **unmapped; no metric invented** |
| `failed_logins` | `ActivityFailedRuns`, `Errors`, `Http4xx`, `PipelineFailedRuns` | covered |
| `function_duration` | `Duration`, `FunctionExecutionUnits` | covered |
| `http_5xx` | — | **unmapped; no metric invented** |
| `ingress_bytes` | `BytesReceived`, `Ingress`, `NetworkIn` | covered |
| `latency` | `AverageResponseTime`, `HttpResponseTime`, `IntegrationRuntimeAverageTaskPickupDelay`, `ServiceApiLatency`, `SuccessE2ELatency`, `SuccessServerLatency` | covered |
| `network_egress_bytes` | `BytesSent`, `Egress`, `NetworkOut` | covered |
| `normal_cpu` | `CPU Credits Consumed`, `CPU Credits Remaining`, `CPUCreditBalance`, `CPUCreditUsage`, `CPUUtilization`, `CpuPercentage`, `CpuUsage`, `IntegrationRuntimeCpuPercentage`, `Percentage CPU`, `compute.googleapis.com/instance/cpu/utilization`, `cpu_percent`, `cpu_usage_idle`, `cpu_usage_iowait`, `cpu_usage_system`, `cpu_usage_user` | covered |
| `normal_requests` | `Requests`, `SuccessfulRequests`, `Transactions`, `storage.googleapis.com/api/request_count` | covered |
| `object_count` | — | **unmapped; no metric invented** |
| `policy_changes` | — | **unmapped; no metric invented** |
| `privileged_api_calls` | `Requests`, `ServiceApiHit`, `SuccessfulRequests`, `Transactions`, `storage.googleapis.com/api/request_count` | covered |
| `region_activity` | — | **unmapped; no metric invented** |
| `regional_error_rate` | `ActivityFailedRuns`, `Errors`, `Http4xx`, `PipelineFailedRuns` | covered |
| `request_count` | `Invocations`, `Requests`, `ServiceApiHit`, `SuccessfulRequests`, `Transactions`, `storage.googleapis.com/api/request_count` | covered |
| `resource_create_count` | — | **unmapped; no metric invented** |
| `security_group_changes` | — | **unmapped; no metric invented** |
| `serverless_invocations` | `ConcurrentExecutions`, `FunctionExecutionCount`, `Invocations` | covered |
| `storage_delete_ops` | — | **unmapped; no metric invented** |
| `storage_reads` | `Composite Disk Read Bytes/sec`, `Composite Disk Read Operations/sec`, `Data Disk Read Bytes/sec`, `Data Disk Read Operations/Sec`, `Disk Read Bytes`, `Disk Read Operations/Sec`, `OS Disk Read Bytes/sec`, `OS Disk Read Operations/Sec`, `Premium Data Disk Cache Read Miss`, `VolumeReadBytes`, `VolumeReadOps`, `VolumeTotalReadTime`, `compute.googleapis.com/instance/disk/read_ops_count` | covered |
| `storage_write_ops` | `Composite Disk Write Operations/sec`, `Disk Write Operations/Sec`, `OS Disk Write Operations/Sec`, `VolumeWriteOps`, `compute.googleapis.com/instance/disk/write_ops_count` | covered |
| `successful_logins` | — | **unmapped; no metric invented** |
| `unusual_egress` | `BytesSent`, `Egress`, `NetworkOut` | covered |

## Provider vocabulary note

The trained `cloud` vocabulary contains: AWS, Azure, GCP.
Providers without a trained cloud category: OCI.
OCI is offered in the synthetic control panel, but this bundle has no OCI cloud category; its categorical cloud embedding may therefore use UNK.

Unmapped metric families are skipped by event generation and logged. This report does not substitute a different metric name.
