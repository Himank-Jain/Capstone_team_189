import { fetchJson, getApiBase, isMockMode } from './apiClient';
import { MOCK_TENANTS } from './mockData';

export interface TenantSummary {
  id: string;
  name: string;
  live_alert_count: number;
  health: string;
}

export async function getTenants(): Promise<TenantSummary[]> {
  if (isMockMode()) return MOCK_TENANTS;
  return fetchJson<TenantSummary[]>(`${getApiBase()}/tenants`);
}
