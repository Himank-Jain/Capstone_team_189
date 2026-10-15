import { fetchJson, getApiBase, getTenantHeaders, isMockMode } from './apiClient';
import { MOCK_ALERTS } from './mockData';
import type { AlertPayload } from '../types/contracts';

export type { AlertPayload } from '../types/contracts';

export async function getRecentAlerts(): Promise<AlertPayload[]> {
  if (isMockMode()) return MOCK_ALERTS;
  return fetchJson<AlertPayload[]>(`${getApiBase()}/alerts/recent`, {
    headers: getTenantHeaders(),
  });
}

export async function getAlertDetails(alertId: string): Promise<AlertPayload> {
  if (isMockMode()) return MOCK_ALERTS.find((alert) => alert.alert_id === alertId) || MOCK_ALERTS[0];
  return fetchJson<AlertPayload>(`${getApiBase()}/alerts/${alertId}`, {
    headers: getTenantHeaders(),
  });
}
