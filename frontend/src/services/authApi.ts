import { fetchJson, getActiveTenantId, getApiBase, getStoredUserId, isMockMode } from './apiClient';
import { MOCK_TENANTS } from './mockData';

export type Role = 'OWNER' | 'OPERATOR' | 'VIEWER';

export interface Membership {
  tenant_id: string;
  tenant_name: string;
  role: Role;
}

export interface SessionUser {
  user_id: string;
  email: string;
  role: Role | null;
  /** Owner of every workspace: can use the Admin console. */
  is_admin?: boolean;
}

export interface AuthSession {
  access_token?: string;
  token_type?: string;
  expires_in?: number;
  user: SessionUser;
  memberships: Membership[];
}

export interface Member {
  user_id: string;
  email: string;
  role: Role;
  joined_at?: string | null;
}

export type AccessLevel = Role | 'NONE';

export interface AccountSummary {
  user_id: string;
  email: string;
  created_at?: string | null;
  is_admin: boolean;
  memberships: Membership[];
}

export const ROLE_RANK: Record<Role, number> = { OWNER: 3, OPERATOR: 2, VIEWER: 1 };
export const MIN_PASSWORD_LENGTH = 8;

// ---------------------------------------------------------------------------
// Mock mode: a small local user directory so sign-in, registration, and member
// management can be exercised without the API. Passwords are stored as SHA-256
// digests, never as plain text, even in this throwaway store.
// ---------------------------------------------------------------------------
const MOCK_USERS_KEY = 'capstone.mock.users';

interface MockUser {
  user_id: string;
  email: string;
  password_digest: string;
  roles: Record<string, Role>;
  created_at: string;
}

function readMockUsers(): MockUser[] {
  try {
    return JSON.parse(localStorage.getItem(MOCK_USERS_KEY) || '[]') as MockUser[];
  } catch {
    return [];
  }
}

function writeMockUsers(users: MockUser[]) {
  try {
    localStorage.setItem(MOCK_USERS_KEY, JSON.stringify(users));
  } catch {
    // ignore: mock directory is best-effort
  }
}

async function digest(value: string): Promise<string> {
  if (typeof crypto !== 'undefined' && crypto.subtle) {
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return Array.from(new Uint8Array(bytes)).map((byte) => byte.toString(16).padStart(2, '0')).join('');
  }
  return `plain:${value.length}:${value}`;
}

function mockIsAdmin(user: MockUser): boolean {
  return MOCK_TENANTS.every((tenant) => user.roles[tenant.id] === 'OWNER');
}

function mockAccount(user: MockUser): AccountSummary {
  return {
    user_id: user.user_id,
    email: user.email,
    created_at: user.created_at,
    is_admin: mockIsAdmin(user),
    memberships: MOCK_TENANTS
      .filter((tenant) => user.roles[tenant.id])
      .map((tenant) => ({ tenant_id: tenant.id, tenant_name: tenant.name, role: user.roles[tenant.id] })),
  };
}

function mockSession(user: MockUser): AuthSession {
  const memberships = MOCK_TENANTS
    .filter((tenant) => user.roles[tenant.id])
    .map((tenant) => ({ tenant_id: tenant.id, tenant_name: tenant.name, role: user.roles[tenant.id] }));
  const role = memberships.reduce<Role | null>(
    (best, item) => (!best || ROLE_RANK[item.role] > ROLE_RANK[best] ? item.role : best),
    null,
  );
  return {
    access_token: `mock-token-${user.user_id}`,
    user: { user_id: user.user_id, email: user.email, role, is_admin: mockIsAdmin(user) },
    memberships,
  };
}

function normalizeEmail(email: string) {
  return email.trim().toLowerCase();
}

function validateCredentials(email: string, password: string) {
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(normalizeEmail(email))) throw new Error('Enter a valid email address');
  if (password.length < MIN_PASSWORD_LENGTH) {
    throw new Error(`Password must be at least ${MIN_PASSWORD_LENGTH} characters`);
  }
}

/** Strip the "HTTP 401: " prefix so forms can show the server's own message. */
export function friendlyError(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) return fallback;
  return error.message.replace(/^HTTP \d+: /, '') || fallback;
}

export async function login(email: string, password: string): Promise<AuthSession> {
  if (isMockMode()) {
    const user = readMockUsers().find((item) => item.email === normalizeEmail(email));
    if (!user || user.password_digest !== await digest(password)) throw new Error('Invalid email or password');
    return mockSession(user);
  }
  return fetchJson<AuthSession>(`${getApiBase()}/auth/login`, {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export async function register(email: string, password: string): Promise<AuthSession> {
  if (isMockMode()) {
    validateCredentials(email, password);
    const users = readMockUsers();
    const normalized = normalizeEmail(email);
    if (users.some((item) => item.email === normalized)) throw new Error('An account with this email already exists');
    const role: Role = users.length === 0 ? 'OWNER' : 'VIEWER';
    const user: MockUser = {
      user_id: `mock-user-${users.length + 1}`,
      email: normalized,
      password_digest: await digest(password),
      roles: Object.fromEntries(MOCK_TENANTS.map((tenant) => [tenant.id, role])),
      created_at: new Date().toISOString(),
    };
    writeMockUsers([...users, user]);
    return mockSession(user);
  }
  return fetchJson<AuthSession>(`${getApiBase()}/auth/register`, {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export async function fetchCurrentSession(): Promise<AuthSession> {
  if (isMockMode()) {
    const user = readMockUsers().find((item) => item.user_id === getStoredUserId());
    if (!user) throw new Error('HTTP 401: Account no longer exists');
    return mockSession(user);
  }
  return fetchJson<AuthSession>(`${getApiBase()}/auth/me`);
}

function mockTenant(): string {
  return getActiveTenantId() || 'google';
}

function requireMockOwner(users: MockUser[]) {
  const actor = users.find((item) => item.user_id === getStoredUserId());
  if (actor?.roles[mockTenant()] !== 'OWNER') throw new Error('HTTP 403: tenant access denied');
}

function ownerCount(users: MockUser[]): number {
  return users.filter((item) => item.roles[mockTenant()] === 'OWNER').length;
}

export async function listMembers(): Promise<Member[]> {
  if (isMockMode()) {
    return readMockUsers()
      .filter((user) => user.roles[mockTenant()])
      .map((user) => ({ user_id: user.user_id, email: user.email, role: user.roles[mockTenant()], joined_at: user.created_at }));
  }
  return fetchJson<Member[]>(`${getApiBase()}/members`);
}

export async function addMember(email: string, role: Role): Promise<Member> {
  if (isMockMode()) {
    const users = readMockUsers();
    requireMockOwner(users);
    const user = users.find((item) => item.email === normalizeEmail(email));
    if (!user) throw new Error('HTTP 404: No account uses that email yet; ask them to register first');
    if (user.roles[mockTenant()]) throw new Error('HTTP 409: That user is already a member');
    user.roles[mockTenant()] = role;
    writeMockUsers(users);
    return { user_id: user.user_id, email: user.email, role, joined_at: new Date().toISOString() };
  }
  return fetchJson<Member>(`${getApiBase()}/members`, {
    method: 'POST',
    body: JSON.stringify({ email, role }),
  });
}

export async function updateMemberRole(userId: string, role: Role): Promise<Member> {
  if (isMockMode()) {
    const users = readMockUsers();
    requireMockOwner(users);
    const user = users.find((item) => item.user_id === userId);
    if (!user?.roles[mockTenant()]) throw new Error('HTTP 404: Member not found');
    if (user.roles[mockTenant()] === 'OWNER' && role !== 'OWNER' && ownerCount(users) <= 1) {
      throw new Error('HTTP 409: A workspace needs at least one owner');
    }
    user.roles[mockTenant()] = role;
    writeMockUsers(users);
    return { user_id: user.user_id, email: user.email, role };
  }
  return fetchJson<Member>(`${getApiBase()}/members/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });
}

export async function removeMember(userId: string): Promise<void> {
  if (isMockMode()) {
    const users = readMockUsers();
    requireMockOwner(users);
    const user = users.find((item) => item.user_id === userId);
    if (!user?.roles[mockTenant()]) throw new Error('HTTP 404: Member not found');
    if (user.roles[mockTenant()] === 'OWNER' && ownerCount(users) <= 1) {
      throw new Error('HTTP 409: A workspace needs at least one owner');
    }
    delete user.roles[mockTenant()];
    writeMockUsers(users);
    return;
  }
  await fetchJson<void>(`${getApiBase()}/members/${encodeURIComponent(userId)}`, { method: 'DELETE' });
}

export async function listAccounts(): Promise<AccountSummary[]> {
  if (isMockMode()) {
    const users = readMockUsers();
    const actor = users.find((item) => item.user_id === getStoredUserId());
    if (!actor || !mockIsAdmin(actor)) throw new Error('HTTP 403: Administrator access required');
    return users.map(mockAccount);
  }
  return fetchJson<AccountSummary[]>(`${getApiBase()}/admin/users`);
}

export async function setAccountAccess(userId: string, role: AccessLevel): Promise<AccountSummary> {
  if (isMockMode()) {
    const users = readMockUsers();
    const actor = users.find((item) => item.user_id === getStoredUserId());
    if (!actor || !mockIsAdmin(actor)) throw new Error('HTTP 403: Administrator access required');
    if (userId === actor.user_id && role !== 'OWNER') throw new Error("HTTP 409: You can't remove your own admin access");
    const user = users.find((item) => item.user_id === userId);
    if (!user) throw new Error('HTTP 404: Account not found');
    MOCK_TENANTS.forEach((tenant) => {
      if (role === 'NONE') delete user.roles[tenant.id];
      else user.roles[tenant.id] = role;
    });
    writeMockUsers(users);
    return mockAccount(user);
  }
  return fetchJson<AccountSummary>(`${getApiBase()}/admin/users/${encodeURIComponent(userId)}/access`, {
    method: 'PUT',
    body: JSON.stringify({ role }),
  });
}
