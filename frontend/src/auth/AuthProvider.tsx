import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  clearSession,
  getAccessToken,
  getActiveTenantId,
  getStoredSessionJson,
  getStoredUserId,
  isMockMode,
  SESSION_EVENT,
  setActiveTenantId,
  setStoredRole,
  storeSession,
} from '../services/apiClient';
import {
  fetchCurrentSession,
  login,
  register,
  type AuthSession,
} from '../services/authApi';
import { MOCK_TENANTS } from '../services/mockData';
import { AuthContext, type AuthContextValue, type AuthStatus } from './authContext';

function readStoredSession(): AuthSession | null {
  const raw = getStoredSessionJson();
  if (raw) {
    try {
      return JSON.parse(raw) as AuthSession;
    } catch {
      return null;
    }
  }
  // Mock-mode smoke tests seed only capstone.userId; give them a usable session.
  const userId = getStoredUserId();
  if (isMockMode() && userId) {
    return {
      user: { user_id: userId, email: `${userId}@mock.local`, role: 'OPERATOR' },
      memberships: MOCK_TENANTS.map((tenant) => ({ tenant_id: tenant.id, tenant_name: tenant.name, role: 'OPERATOR' })),
    };
  }
  return null;
}

function chooseTenant(session: AuthSession): string | null {
  const current = getActiveTenantId();
  if (current && session.memberships.some((item) => item.tenant_id === current)) return current;
  return session.memberships[0]?.tenant_id ?? null;
}

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(() => readStoredSession());
  const [status, setStatus] = useState<AuthStatus>(() => {
    if (!readStoredSession()) return 'anonymous';
    return getAccessToken() ? 'loading' : 'authenticated';
  });
  const [activeTenantId, setActiveTenant] = useState<string | null>(() => getActiveTenantId());

  const apply = useCallback((next: AuthSession, token: string | null) => {
    const tenantId = chooseTenant(next);
    const role = next.memberships.find((item) => item.tenant_id === tenantId)?.role ?? null;
    if (tenantId) setActiveTenantId(tenantId);
    storeSession({
      token,
      userId: next.user.user_id,
      sessionJson: JSON.stringify({ user: next.user, memberships: next.memberships }),
      role,
    });
    setSession(next);
    setActiveTenant(tenantId);
    setStatus('authenticated');
  }, []);

  const refresh = useCallback(async () => {
    const token = getAccessToken();
    if (!token) return;
    try {
      apply(await fetchCurrentSession(), token);
    } catch {
      clearSession();
      setSession(null);
      setStatus('anonymous');
    }
  }, [apply]);

  // Revalidate a stored token once on load (it may have expired or been revoked).
  useEffect(() => {
    const token = getAccessToken();
    if (!token || !getStoredUserId()) return undefined;
    let cancelled = false;
    fetchCurrentSession()
      .then((next) => { if (!cancelled) apply(next, token); })
      .catch(() => {
        if (cancelled) return;
        clearSession();
        setSession(null);
        setStatus('anonymous');
      });
    return () => {
      cancelled = true;
    };
  }, [apply]);

  // Stay in sync with other tabs and with apiClient clearing an expired session.
  useEffect(() => {
    const sync = () => {
      const stored = readStoredSession();
      setActiveTenant(getActiveTenantId());
      if (!stored) {
        setSession(null);
        setStatus('anonymous');
      }
    };
    window.addEventListener(SESSION_EVENT, sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener(SESSION_EVENT, sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  const value = useMemo<AuthContextValue>(() => {
    const activeMembership = session?.memberships.find((item) => item.tenant_id === activeTenantId) ?? null;
    return {
      status,
      session,
      activeTenantId,
      activeMembership,
      role: activeMembership?.role ?? null,
      signIn: async (email, password) => {
        const next = await login(email, password);
        apply(next, next.access_token ?? null);
        return next;
      },
      signUp: async (email, password) => {
        const next = await register(email, password);
        apply(next, next.access_token ?? null);
        return next;
      },
      signOut: () => {
        clearSession();
        setSession(null);
        setStatus('anonymous');
      },
      switchTenant: (tenantId: string) => {
        const membership = session?.memberships.find((item) => item.tenant_id === tenantId);
        setActiveTenantId(tenantId);
        setStoredRole(membership?.role ?? null);
        setActiveTenant(tenantId);
      },
      refresh,
    };
  }, [activeTenantId, apply, refresh, session, status]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
