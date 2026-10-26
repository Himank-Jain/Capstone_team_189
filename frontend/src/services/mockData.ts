import type { AlertPayload } from '../types/contracts';

export const MOCK_TENANTS = [
  { id: 'google', name: 'Google Demo', live_alert_count: 1, health: 'healthy' },
  { id: 'amazon', name: 'Amazon Demo', live_alert_count: 0, health: 'healthy' },
  { id: 'microsoft', name: 'Microsoft Demo', live_alert_count: 0, health: 'healthy' },
];

export const MOCK_ALERTS: AlertPayload[] = [
  {
    alert_id: 'demo-high-confidence',
    entity_id: 'vol-g00g',
    batch_ts: '2026-10-09T09:42:00Z',
    final_score: 0.91,
    severity: 'CRITICAL',
    sev_level: 'SEV1',
    deviation_score: 0.88,
    drift_score: 0.71,
    similarity_score: 0.24,
    similar_episodes: [],
    related_ids: [],
    group_type: 'ISOLATED',
    target_team: 'cloud-security',
    notify_method: 'PAGE',
    cloud_provider: 'GCP',
    region: 'us-central1',
  },
];
