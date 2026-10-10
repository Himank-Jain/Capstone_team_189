import { fetchJson, getApiBase } from './apiClient';

export interface TenantSummary {
  id: string;
  name: string;
  live_alert_count: number;
  health: string;
}

export async function getTenants(): Promise<TenantSummary[]> {
  return fetchJson<TenantSummary[]>(`${getApiBase()}/tenants`);
}
