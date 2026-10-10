import { fetchJson, getApiBase, getTenantHeaders } from './apiClient';

export interface AlertPayload {
  alert_id: string;
  entity_id: string;
  batch_ts: string;
  final_score: number;
  severity: string;
  sev_level: string;
  deviation_score: number;
  drift_score: number;
  similarity_score: number;
  similar_episodes: Array<Record<string, unknown>>;
  related_ids: string[];
  group_type: string;
  target_team: string;
  notify_method: string;
  cloud_provider: string;
  region: string;
}

export async function getRecentAlerts(): Promise<AlertPayload[]> {
  return fetchJson<AlertPayload[]>(`${getApiBase()}/alerts/recent`, {
    headers: getTenantHeaders(),
  });
}

export async function getAlertDetails(alertId: string): Promise<AlertPayload> {
  return fetchJson<AlertPayload>(`${getApiBase()}/alerts/${alertId}`, {
    headers: getTenantHeaders(),
  });
}
