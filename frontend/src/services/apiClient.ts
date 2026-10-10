const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8001";
const TENANT_KEY = "capstone.activeTenantId";

export function getApiBase() {
  return API_BASE;
}

export function setActiveTenantId(tenantId: string) {
  localStorage.setItem(TENANT_KEY, tenantId);
}

export function getActiveTenantId(): string | null {
  return localStorage.getItem(TENANT_KEY);
}

export function getTenantHeaders(): Record<string, string> {
  let tenantId = getActiveTenantId();
  if (!tenantId) {
    tenantId = 'google';
    setActiveTenantId(tenantId);
  }
  return { "X-Tenant-Id": tenantId };
}

export async function fetchJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const headers = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  const response = await fetch(input, { ...init, headers });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status}: ${text}`);
  }
  return response.json() as Promise<T>;
}
