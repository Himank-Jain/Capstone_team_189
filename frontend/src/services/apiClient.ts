const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8001";
const TENANT_KEY = "capstone.activeTenantId";
const USER_KEY = "capstone.userId";
const TOKEN_KEY = "capstone.accessToken";
const ROLE_KEY = "capstone.role";
const SESSION_KEY = "capstone.session";
const MOCK_MODE = import.meta.env.VITE_MOCK_MODE === 'true';

/** Fired on window whenever the stored session is replaced or cleared. */
export const SESSION_EVENT = 'capstone:session';

export function isMockMode(): boolean {
  return MOCK_MODE;
}

export function getApiBase() {
  return API_BASE;
}

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable (private mode); the in-memory session still works.
  }
}

export function setActiveTenantId(tenantId: string) {
  writeStorage(TENANT_KEY, tenantId);
  window.dispatchEvent(new Event(SESSION_EVENT));
}

export function getActiveTenantId(): string | null {
  return readStorage(TENANT_KEY);
}

export function getAccessToken(): string | null {
  return readStorage(TOKEN_KEY);
}

export function getStoredUserId(): string | null {
  return readStorage(USER_KEY);
}

export function getStoredSessionJson(): string | null {
  return readStorage(SESSION_KEY);
}

export function storeSession(params: {
  token: string | null;
  userId: string;
  sessionJson: string;
  role: string | null;
}) {
  writeStorage(TOKEN_KEY, params.token);
  writeStorage(USER_KEY, params.userId);
  writeStorage(SESSION_KEY, params.sessionJson);
  writeStorage(ROLE_KEY, params.role);
  window.dispatchEvent(new Event(SESSION_EVENT));
}

export function setStoredRole(role: string | null) {
  writeStorage(ROLE_KEY, role);
}

export function clearSession() {
  [TOKEN_KEY, USER_KEY, SESSION_KEY, ROLE_KEY, 'capstone.refreshToken'].forEach((key) => writeStorage(key, null));
  window.dispatchEvent(new Event(SESSION_EVENT));
}

export function getAuthHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function getTenantHeaders(): Record<string, string> {
  let tenantId = getActiveTenantId();
  if (!tenantId) {
    tenantId = 'google';
    writeStorage(TENANT_KEY, tenantId);
  }
  const userId = getStoredUserId();
  return {
    "X-Tenant-Id": tenantId,
    ...(userId ? { "X-User-Id": userId } : {}),
    ...getAuthHeaders(),
  };
}

function isAuthEndpoint(input: RequestInfo): boolean {
  const url = typeof input === 'string' ? input : input.url;
  return /\/auth\/(login|register)$/.test(url);
}

/** Session expired or revoked: drop it and send the user back to sign in. */
function handleUnauthorized() {
  clearSession();
  if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
    window.location.assign('/login?expired=1');
  }
}

async function errorDetail(response: Response): Promise<string> {
  const text = await response.text();
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === 'string') return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      return parsed.detail
        .map((item) => (item && typeof item === 'object' && 'msg' in item ? String(item.msg) : String(item)))
        .join('; ');
    }
  } catch {
    // Not JSON; fall through to the raw text.
  }
  return text;
}

/**
 * JSON fetch that sends the tenant, user, and bearer-token headers by default.
 * Errors keep the "HTTP <status>: <detail>" shape existing pages match on.
 */
export async function fetchJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const headers = {
    "Content-Type": "application/json",
    ...getTenantHeaders(),
    ...(init?.headers as Record<string, string> | undefined),
  };
  const response = await fetch(input, { ...init, headers });
  if (response.status === 401 && !isAuthEndpoint(input)) {
    handleUnauthorized();
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${await errorDetail(response)}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
