import { getTenantHeaders } from './apiClient';

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8001";
// expose for debugging in the browser console
console.info('[demoApi] API_BASE =', API_BASE);

export interface DemoTenant {
  id: string;
  name: string;
  live_alert_count: number;
  health: string;
}

export interface DemoScenario {
  value: string;
  label: string;
  description: string;
  category: string;
  default_notify_method: string;
  severity: string;
}

export type NotifyMethod = 'PAGE' | 'SLACK' | 'EMAIL';

export interface DemoAlertResponse {
  status: string;
  tenant_id: string;
  scenario: string;
  mode: string;
  notify_method: NotifyMethod;
  notification?: {
    notify_method: string;
    status: string;
    message: string;
    email_to?: string;
  };
  alert_payload: Record<string, unknown>;
  heartbeat: Record<string, unknown>;
  explainable_api: string;
}

export interface DemoStatusResponse {
  tenant_id: string;
  paused: boolean;
  active_alerts: number;
}

export interface SummaryPayload {
  model_confidence: number;
  critical_alerts: number;
  [key: string]: unknown;
}

export async function getDemoTenants(): Promise<DemoTenant[]> {
  const res = await fetch(`${API_BASE}/tenants`);
  if (!res.ok) throw new Error(`Tenants API error: ${res.status}`);
  return res.json();
}

export async function getSummary(): Promise<SummaryPayload> {
  const res = await fetch(`${API_BASE}/stats/summary`, {
    headers: getTenantHeaders(),
  });
  if (!res.ok) throw new Error(`Stats API error: ${res.status}`);
  return res.json();
}

export async function getDemoScenarios(): Promise<DemoScenario[]> {
  const res = await fetch(`${API_BASE}/demo/scenarios`);
  if (!res.ok) throw new Error(`Scenarios API error: ${res.status}`);
  return res.json();
}

export async function getNotifyMethods(): Promise<NotifyMethod[]> {
  const res = await fetch(`${API_BASE}/demo/notify-methods`);
  if (!res.ok) throw new Error(`Notify methods API error: ${res.status}`);
  return res.json();
}

export async function triggerDemoAlert(tenant_id: string, scenario: string, notify_method: NotifyMethod, mode: 'attack' | 'normal'): Promise<DemoAlertResponse> {
  const res = await fetch(`${API_BASE}/demo/generate/alert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getTenantHeaders() },
    body: JSON.stringify({ tenant_id, scenario, notify_method, mode }),
  });
  if (!res.ok) throw new Error(`Demo API error: ${res.status}`);
  return res.json();
}

export async function triggerDemoScenario(tenant_id: string, scenario: string) {
  const res = await fetch(`${API_BASE}/demo/generate/attack`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getTenantHeaders() },
    body: JSON.stringify({ tenant_id, scenario }),
  });
  if (!res.ok) throw new Error(`Demo API error: ${res.status}`);
  return res.json();
}

export async function getDemoStatus(): Promise<DemoStatusResponse> {
  const res = await fetch(`${API_BASE}/demo/status`, {
    headers: getTenantHeaders(),
  });
  if (!res.ok) throw new Error(`Demo status API error: ${res.status}`);
  return res.json();
}

export async function pauseDemo(): Promise<DemoStatusResponse> {
  const res = await fetch(`${API_BASE}/demo/pause`, {
    method: 'POST',
    headers: getTenantHeaders(),
  });
  if (!res.ok) throw new Error(`Demo pause API error: ${res.status}`);
  return res.json();
}

export async function resumeDemo(): Promise<DemoStatusResponse> {
  const res = await fetch(`${API_BASE}/demo/resume`, {
    method: 'POST',
    headers: getTenantHeaders(),
  });
  if (!res.ok) throw new Error(`Demo resume API error: ${res.status}`);
  return res.json();
}

export async function resetDemo(): Promise<DemoStatusResponse> {
  const res = await fetch(`${API_BASE}/demo/reset`, {
    method: 'POST',
    headers: getTenantHeaders(),
  });
  if (!res.ok) throw new Error(`Demo reset API error: ${res.status}`);
  return res.json();
}

export async function callExplainableApi(apiPath: string, alert_payload: Record<string, unknown>): Promise<any> {
  // Resolve the explainable API URL relative to the configured API base
  let url = apiPath;
  if (!/^https?:\/\//i.test(apiPath)) {
    if (!apiPath.startsWith('/')) apiPath = '/' + apiPath;
    url = `${API_BASE}${apiPath}`;
  }

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getTenantHeaders() },
    body: JSON.stringify(alert_payload),
  });
  if (!res.ok) throw new Error(`Explainable API error: ${res.status}`);
  return res.json();
}
